"""Save a real pre-MiniMax task checkpoint backed by existing test evidence."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    baseline = ROOT / "evidence/baseline"
    report = json.loads((baseline / "report.json").read_text(encoding="utf-8"))
    for name, expected in report["sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise SystemExit("Original sample changed; do not reuse pre-change evidence")
    validations = []
    for name, run in report["runs"].items():
        log_path = baseline / f"{name}.log"
        validations.append({
            "command": run["command"], "exit_code": run["exit_code"],
            "log_path": str(log_path.relative_to(ROOT)),
            "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        })
    state = {
        "task_id": "order-status-filter",
        "objective": "Implement status filtering before pagination while preserving existing order query behavior.",
        "completed": ["Business specification and baseline implementation created",
                      "Pre-change target and regression test results recorded",
                      "Engineering sources imported into seekdb and retrieval verified"],
        "pending": ["Use MiniMax with the retrieved context to implement status filtering",
                    "Run the unchanged target tests and regression tests after modification",
                    "Record MiniMax usage, code diff and final verification evidence"],
        "validations": validations,
    }
    path = ROOT / "runtime" / "task-state-input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return subprocess.call([sys.executable, "-m", "sdd_context", "--project-root", str(ROOT),
                            "state-save", "--input", str(path)], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
