"""Reproduce recorded before/after behavior without calling any model."""

from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True, help="Recorded evidence/minimax/<run-id> directory")
    args = parser.parse_args()
    source = (ROOT / args.run).resolve()
    report = json.loads((source / "report.json").read_text())
    if not report.get("passed"):
        raise SystemExit("Select a successful recorded run")
    if digest(source / "before.py") != report["before_sha256"]:
        raise SystemExit("Before snapshot does not match the recorded digest")
    if digest(source / "after.py") != report["after_sha256"]:
        raise SystemExit("After snapshot does not match the recorded digest")
    for name, expected in report["tests_sha256_before"].items():
        if digest(ROOT / name) != expected or report["tests_sha256_after"][name] != expected:
            raise SystemExit("Acceptance tests differ from the original run")
    output = ROOT / "evidence" / "replay" / uuid.uuid4().hex
    output.mkdir(parents=True)
    result = {"source_run": report["run_id"], "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "model_called": False, "passed": False, "runs": {}}
    with tempfile.TemporaryDirectory(prefix="minimax-clean-sample-") as directory:
        clean = Path(directory)
        (clean / "sample_project").mkdir()
        (clean / "sample_project/__init__.py").write_text("")
        (clean / "tests").mkdir()
        for name in report["tests_sha256_before"]:
            shutil.copyfile(ROOT / name, clean / name)
        for phase, snapshot in (("before", "before.py"), ("after", "after.py")):
            shutil.copyfile(source / snapshot, clean / "sample_project/orders.py")
            for name in ("target", "regression"):
                # -S disables site-packages: the business sample must need only stdlib.
                command = [sys.executable, "-S", "-B", "-m", "unittest", "discover", "-s", "tests",
                           "-p", f"test_{name}.py", "-v"]
                proc = subprocess.run(command, cwd=clean, capture_output=True, text=True, timeout=30)
                log = output / f"{phase}-{name}.log"
                log.write_text(proc.stdout + proc.stderr, encoding="utf-8")
                result["runs"][f"{phase}-{name}"] = {"command": command, "exit_code": proc.returncode,
                                                       "log_sha256": digest(log)}
            # Prevent Python timestamp-based cache reuse across before/after copies.
            shutil.rmtree(clean / "sample_project/__pycache__", ignore_errors=True)
        runs = result["runs"]
        result["passed"] = (runs["before-target"]["exit_code"] != 0
                            and all(runs[name]["exit_code"] == 0 for name in
                                    ("before-regression", "after-target", "after-regression")))
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "model_called": False,
                      "evidence": str(output.relative_to(ROOT))}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
