"""Record the genuine pre-MiniMax behavior; never generates passing evidence."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "evidence" / "baseline"
    if output.exists():
        raise SystemExit("Baseline already exists; refusing to overwrite original evidence.")
    output.mkdir(parents=True)
    git_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    sources = [
        "sample_project/orders.py", "specs/orders-v1.md",
        "tasks/order-status-filter.md", "tests/test_regression.py", "tests/test_target.py",
    ]
    hashes = {}
    for source in sources:
        data = (ROOT / source).read_bytes()
        hashes[source] = hashlib.sha256(data).hexdigest()
        destination = output / "snapshot" / source
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    runs = {}
    for name in ("regression", "target"):
        command = [sys.executable, "-m", "unittest", "discover", "-s", "tests",
                   "-p", f"test_{name}.py", "-v"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        (output / f"{name}.log").write_text(
            result.stdout + result.stderr, encoding="utf-8"
        )
        runs[name] = {"command": command, "exit_code": result.returncode}
    report = {
        "stage": "before_minimax_change", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "git_base_commit": git_head,
        "source_identity": "working-tree SHA-256 and exact snapshots; not a committed implementation",
        "sha256": hashes, "runs": runs,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(runs, indent=2))
    if runs["regression"]["exit_code"] != 0 or runs["target"]["exit_code"] == 0:
        raise SystemExit("Unexpected baseline. Inspect logs; evidence is not accepted.")
    print("Baseline recorded: regression passes; status-filter feature is not implemented.")


if __name__ == "__main__":
    main()
