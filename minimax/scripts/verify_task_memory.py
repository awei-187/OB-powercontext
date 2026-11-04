"""Verify PowerContext persistence and reuse through separate CLI processes."""

from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from sdd_context.provenance import source_identity

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    run_id = uuid.uuid4().hex
    checks, processes = [], []
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "powercontext_version": version("powercontext"),
              "command": [sys.executable, "scripts/verify_task_memory.py"],
              **source_identity(ROOT), "passed": False}
    try:
        with tempfile.TemporaryDirectory(prefix="minimax-task-memory-") as directory:
            temp = Path(directory)
            state_dir = temp / "powercontext"
            task_id = "verification-" + run_id

            def run(*args, expected=0, manifest=None):
                command = [sys.executable, "-m", "sdd_context", "--project-root", str(ROOT),
                           "--state-dir", str(state_dir)]
                if manifest:
                    command += ["--manifest", str(manifest)]
                command += list(args)
                # State APIs do not need MiniMax or any inference provider configuration.
                env = {k: v for k, v in os.environ.items()
                       if not k.startswith(("MINIMAX_", "OPENAI_", "ANTHROPIC_"))}
                result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True,
                                        timeout=90)
                processes.append({"command": command, "exit_code": result.returncode,
                                  "stdout": result.stdout, "stderr": result.stderr})
                require(result.returncode == expected,
                        f"Subprocess exited {result.returncode}: {result.stderr[-1200:]}")
                return json.loads(result.stdout) if expected == 0 else None

            empty = run("state-show", "--task-id", task_id)
            require(not empty["found"], "New state directory should contain no task")
            checks.append("Fresh PowerContext storage returns no fabricated progress")
            state = {"task_id": task_id, "objective": "Integration fixture: verify restart persistence",
                     "completed": ["Integration fixture checkpoint A"],
                     "pending": ["Integration fixture next action B"], "validations": []}
            input_path = temp / "state.json"
            input_path.write_text(json.dumps(state), encoding="utf-8")
            saved = run("state-save", "--input", str(input_path))
            require((state_dir / "memory.db").exists(), "Real PowerContext SQLite database was not created")
            restored = run("state-show", "--task-id", task_id)
            require(restored["found"] and restored["task_progress"]["state"] == state,
                    "Independent reader did not recover the saved state")
            require(saved["citation"] == restored["task_progress"]["citation"], "Citation changed on read")
            checks.append("Writer exits; independent process restores exact state and PowerContext citation")

            prepared = run("prepare", "--task", "tasks/order-status-filter.md", "--task-id", task_id)
            require(prepared["ready_for_development"] and prepared["sources"], "seekdb retrieval failed")
            require(prepared["task_progress"]["state"] == state, "Saved state was not used in next context")
            require(prepared["task_progress"]["citation"] == saved["citation"], "Context lost citation")
            checks.append("A new prepare process combines seekdb sources with restored PowerContext progress")

            state["completed"].append("Integration fixture checkpoint C")
            state["pending"] = ["Integration fixture replacement action D"]
            input_path.write_text(json.dumps(state), encoding="utf-8")
            updated = run("state-save", "--input", str(input_path))
            latest = run("state-show", "--task-id", task_id)["task_progress"]
            require(latest["state"] == state, "Outdated state remained current")
            require(updated["citation"]["entry_id"] == saved["citation"]["entry_id"],
                    "Update should revise the existing logical Memory entry")
            require(updated["citation"]["entry_version_id"] != saved["citation"]["entry_version_id"],
                    "Update should create an immutable Memory version")
            checks.append("Updated progress revises the same Memory entry and restores the new version")

            manifest = json.loads((ROOT / "project.json").read_text())
            manifest["project_id"] = "other-" + run_id
            manifest_path = temp / "other-project.json"
            manifest_path.write_text(json.dumps(manifest))
            isolated = run("state-show", "--task-id", task_id, manifest=manifest_path)
            require(not isolated["found"], "State leaked into another project")
            require(not run("state-show", "--task-id", "other-task-" + run_id)["found"],
                    "State leaked into another task")
            checks.append("Project and task scopes are independently isolated")

            invalid = dict(state, unexpected_field=True)
            input_path.write_text(json.dumps(invalid))
            run("state-save", "--input", str(input_path), expected=1)
            require(run("state-show", "--task-id", task_id)["task_progress"]["state"] == state,
                    "Invalid save altered previously committed progress")
            checks.append("Rejected state input preserves previously committed progress")
            report["passed"] = True
    finally:
        report.update({"checks": checks, "processes": processes})
        output = ROOT / "evidence" / "task-memory"
        output.mkdir(parents=True, exist_ok=True)
        path = output / f"verification-{run_id}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "checks": checks,
                          "report": str(path.relative_to(ROOT))}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
