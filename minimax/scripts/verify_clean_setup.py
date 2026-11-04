"""Verify delivery against a brand-new isolated Docker Compose database."""

from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    run_id = uuid.uuid4().hex
    output = ROOT / "evidence" / "clean-setup" / run_id
    output.mkdir(parents=True)
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "passed": False,
              "isolation": "new Compose container, volume, database and credentials", "commands": []}
    with tempfile.TemporaryDirectory(prefix="minimax-compose-") as directory:
        directory = Path(directory)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env_file = directory / ".env"
        root_password, app_password = secrets.token_hex(24), secrets.token_hex(24)
        env_file.write_text(f"SEEKDB_HOST=127.0.0.1\nSEEKDB_PORT={port}\n"
                            "SEEKDB_DATABASE=minimax_sdd\nSEEKDB_USER=minimax_app\n"
                            f"SEEKDB_ROOT_PASSWORD={root_password}\nSEEKDB_PASSWORD={app_password}\n")
        env_file.chmod(0o600)
        compose = ["docker", "compose", "--project-name", "minimax-verify-" + run_id,
                   "--env-file", str(env_file), "-f", str(ROOT / "compose.yaml")]

        def run(command, name, timeout=180):
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
            text = (result.stdout + result.stderr).replace(root_password, "[REDACTED]").replace(app_password, "[REDACTED]")
            (output / f"{name}.log").write_text(text, encoding="utf-8")
            report["commands"].append({"command": command, "exit_code": result.returncode, "log": f"{name}.log"})
            if result.returncode:
                raise RuntimeError(f"Clean setup step failed: {name}")
            return result.stdout

        try:
            run(compose + ["up", "-d"], "compose-up")
            run([sys.executable, "scripts/bootstrap_database.py", "--env-file", str(env_file)], "bootstrap")
            run([sys.executable, "-m", "sdd_context", "--env-file", str(env_file), "ingest"], "ingest")
            prepared = json.loads(run([sys.executable, "-m", "sdd_context", "--env-file", str(env_file),
                                      "prepare", "--task", "tasks/order-status-filter.md"], "prepare"))
            if not prepared["ready_for_development"] or len(prepared["sources"]) != 4:
                raise RuntimeError("Clean database did not return the required source set")
            run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
                "all-tests")
            report["passed"] = True
        finally:
            # This project name is generated for this run only; never touch the user's main instance.
            try:
                run(compose + ["down", "--volumes"], "compose-cleanup")
            finally:
                (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                print(json.dumps({"passed": report["passed"], "evidence": str(output.relative_to(ROOT))}, indent=2))


if __name__ == "__main__":
    main()
