"""Reproduce the exported delivery without original credentials, venv or Git metadata."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("sdd_context", "sample_project", "tests", "scripts", "specs", "tasks", "evidence")
SOURCE_FILES = ("pyproject.toml", "uv.lock", "project.json", "compose.yaml", ".env.example",
                ".gitignore", "README.md", "TECHNICAL.md", "ACCEPTANCE.md")
RECORDED_RUN = "evidence/minimax/20261104T085127Z-f73a571f"


def export_paths():
    for name in SOURCE_FILES:
        path = ROOT / name
        if path.is_file():
            yield path
    for name in SOURCE_DIRS:
        for path in sorted((ROOT / name).rglob("*")):
            relative = path.relative_to(ROOT)
            if (path.is_file() and not path.is_symlink()
                    and not any(part in ("__pycache__", ".venv", "runtime", ".git", ".env")
                                or part.endswith(".egg-info") for part in relative.parts)
                    and path.suffix not in (".pyc", ".pyo")
                    and relative.parts[:2] != ("evidence", "delivery")):
                yield path


def main():
    uv = shutil.which("uv") or "/home/research/.local/bin/uv"
    if not Path(uv).is_file():
        raise SystemExit("Install uv before running delivery verification")
    run_id = uuid.uuid4().hex
    output = ROOT / "evidence/delivery" / run_id
    output.mkdir(parents=True)
    report = {"run_id": run_id, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "passed": False, "model_called": False, "commands": [], "export_sha256": {},
              "isolation": "exported files only; new venv, Compose database/volume, credentials and PowerContext storage"}
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(("SEEKDB_", "MINIMAX_", "OPENAI_", "ANTHROPIC_", "POWERCONTEXT_"))
                   and k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "MMX_CONFIG_DIR")}
    started = False
    with tempfile.TemporaryDirectory(prefix="minimax-delivery-") as directory:
        clean = Path(directory) / "minimax"
        clean.mkdir()
        for path in export_paths():
            relative = path.relative_to(ROOT)
            target = clean / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            report["export_sha256"][str(relative)] = hashlib.sha256(target.read_bytes()).hexdigest()
        if (clean / ".git").exists() or (clean / ".venv").exists() or (clean / ".env").exists():
            raise RuntimeError("Unexpected local state in delivery export")
        original_evidence = {str(p.relative_to(clean)) for p in (clean / "evidence").rglob("*") if p.is_file()}
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        root_password, app_password = secrets.token_hex(24), secrets.token_hex(24)
        config = clean / ".env"
        config.write_text(f"SEEKDB_HOST=127.0.0.1\nSEEKDB_PORT={port}\nSEEKDB_DATABASE=minimax_sdd\n"
                          f"SEEKDB_USER=minimax_app\nSEEKDB_PASSWORD={app_password}\n"
                          f"SEEKDB_ROOT_PASSWORD={root_password}\n", encoding="utf-8")
        config.chmod(0o600)
        compose = ["docker", "compose", "--project-name", "minimax-delivery-" + run_id,
                   "--env-file", str(config), "-f", str(clean / "compose.yaml")]

        def run(command, name, timeout=300):
            try:
                proc = subprocess.run(command, cwd=clean, env=environment,
                                      capture_output=True, text=True, timeout=timeout)
                text = proc.stdout + proc.stderr
                status = proc.returncode
            except subprocess.TimeoutExpired as exc:
                text = "Timed out during " + name
                status = -1
            for secret in (root_password, app_password):
                text = text.replace(secret, "[REDACTED]")
            log = output / f"{name}.log"
            log.write_text(text, encoding="utf-8")
            report["commands"].append({"command": command, "cwd": str(clean), "exit_code": status,
                                       "log": log.name, "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
            if status:
                raise RuntimeError(f"Delivery step failed: {name}; see {log.name}")
            print("PASS: " + name, flush=True)
            return proc.stdout

        try:
            run([uv, "sync", "--locked", "--python", "/usr/bin/python3"], "fresh-install", timeout=600)
            python = str(clean / ".venv/bin/python")
            report["fresh_venv_created"] = (clean / ".venv/pyvenv.cfg").is_file()
            started = True
            run(compose + ["up", "-d"], "compose-up")
            run([python, "scripts/bootstrap_database.py"], "bootstrap")
            run([python, "-m", "sdd_context", "ingest"], "ingest")
            prepared = json.loads(run([python, "-m", "sdd_context", "prepare", "--task", TASK], "prepare"))
            if not prepared["ready_for_development"] or len(prepared["sources"]) != 4:
                raise RuntimeError("Missing required engineering sources")
            run([python, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"], "all-tests")
            run([python, "scripts/verify_context.py"], "context-integration")
            run([python, "scripts/verify_task_memory.py"], "powercontext-process-restart")
            run([python, "scripts/replay_evidence.py", "--run", RECORDED_RUN], "before-after-replay")
            report["passed"] = True
        except Exception as exc:
            report["failure"] = str(exc)
            raise
        finally:
            try:
                if started:
                    run(compose + ["down", "--volumes"], "compose-cleanup")
            finally:
                for path in (clean / "evidence").rglob("*"):
                    relative = path.relative_to(clean)
                    if path.is_file() and str(relative) not in original_evidence:
                        destination = output / "generated-evidence" / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, destination)
                report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
                (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(json.dumps({"passed": report["passed"], "report": str((output / "report.json").relative_to(ROOT))}))


TASK = "tasks/order-status-filter.md"
if __name__ == "__main__":
    main()
