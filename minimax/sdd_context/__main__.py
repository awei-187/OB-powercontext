import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

import pymysql

from .config import Settings
from .documents import load_manifest, read_documents
from .store import Store


def parser():
    result = argparse.ArgumentParser(description="seekdb-backed engineering context")
    result.add_argument("--project-root", type=Path, default=Path.cwd())
    result.add_argument("--manifest", default="project.json")
    result.add_argument("--env-file", type=Path)
    result.add_argument("--state-dir", type=Path, help="PowerContext local storage (default: runtime/powercontext)")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("ingest", help="Atomically import the manifest's current document set")
    prepare = commands.add_parser("prepare", help="Retrieve current source text from seekdb")
    group = prepare.add_mutually_exclusive_group(required=True)
    group.add_argument("--task", type=Path)
    group.add_argument("--query")
    prepare.add_argument("--per-role", type=int, default=2)
    prepare.add_argument("--task-id", help="Restore this task's progress into the development context")
    save = commands.add_parser("state-save", help="Persist task progress through PowerContext Memory")
    save.add_argument("--input", type=Path, required=True)
    show = commands.add_parser("state-show", help="Read task progress through PowerContext Memory")
    show.add_argument("--task-id", required=True)
    return result


def main():
    args = parser().parse_args()
    store = None
    try:
        root = args.project_root.resolve()
        manifest = load_manifest(root / args.manifest)
        state_dir = root / args.state_dir if args.state_dir else root / "runtime" / "powercontext"
        # Validate local files before opening a database transaction.
        if args.command == "ingest":
            documents = read_documents(root, manifest)
        elif args.command == "prepare":
            query = ((root / args.task).read_text(encoding="utf-8") if args.task
                     else args.query).strip()
            if not query or len(query.encode()) > 20_000:
                raise ValueError("Query must contain 1..20000 UTF-8 bytes")
            if not 1 <= args.per_role <= 5:
                raise ValueError("--per-role must be between 1 and 5")
        if args.command in ("state-save", "state-show"):
            from .task_memory import TaskState, load_state, save_state
            if args.command == "state-save":
                state = TaskState.model_validate_json((root / args.input).read_text(encoding="utf-8"))
                result = asyncio.run(save_state(state_dir, manifest["project_id"], state))
            else:
                restored = asyncio.run(load_state(state_dir, manifest["project_id"], args.task_id))
                result = {"found": restored is not None, "task_progress": restored}
        else:
            settings = Settings.load(args.env_file or root / ".env")
            store = Store(settings)
            if args.command == "ingest":
                result = store.ingest(manifest["project_id"], documents)
            else:
                result = store.prepare(manifest["project_id"], query, args.per_role)
                if args.task_id:
                    from .task_memory import load_state
                    result["task_progress"] = asyncio.run(
                        load_state(state_dir, manifest["project_id"], args.task_id))
                    result["task_progress_found"] = result["task_progress"] is not None
        timestamp = datetime.now(timezone.utc).isoformat()
        result["timestamp_utc"] = timestamp
        audit = root / "runtime" / "queries"
        audit.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4().hex
        audit_path = audit / f"{args.command}-{run_id}.json"
        audit_path.write_text(json.dumps({"timestamp_utc": timestamp, "command": args.command,
                                         "result": result, "queries": store.queries if store else []},
                                        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["audit_file"] = str(audit_path.relative_to(root))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "prepare" and not result["ready_for_development"]:
            return 2
        return 0
    except (ValueError, OSError, pymysql.MySQLError) as exc:
        # Avoid printing connection errors verbatim: some drivers include account details.
        if isinstance(exc, pymysql.MySQLError):
            print(f"seekdb operation failed ({type(exc).__name__}, code={exc.args[0]}). "
                  "Check database availability and local settings.", file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
