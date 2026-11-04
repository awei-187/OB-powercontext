"""Record completed local validation without claiming official acceptance."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from sdd_context.documents import load_manifest
from sdd_context.task_memory import TaskState, load_state, save_state

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean-report", type=Path, required=True)
    parser.add_argument("--replay-report", type=Path, required=True)
    args = parser.parse_args()
    clean = json.loads((ROOT / args.clean_report).read_text())
    replay = json.loads((ROOT / args.replay_report).read_text())
    if not clean["passed"] or not replay["passed"]:
        raise ValueError("Cannot finalize unsuccessful validation")
    project = load_manifest(ROOT / "project.json")["project_id"]
    directory = ROOT / "runtime/powercontext"
    progress = await load_state(directory, project, "order-status-filter")
    if not progress:
        raise ValueError("Missing existing task state")
    state = TaskState.model_validate(progress["state"])
    if not any("MiniMax generated" in item for item in state.completed):
        raise ValueError("MiniMax implementation must be completed first")
    milestone = "Independent Compose database, snapshot replay and local delivery documentation verified"
    if milestone not in state.completed:
        state.completed.append(milestone)
    state.pending = ["Review and commit/push the local deliverable to the competition repository",
                     "Submit the fixed commit on the competition platform; official acceptance is pending"]
    saved = await save_state(directory, project, state)
    output = ROOT / "evidence" / "delivery-progress.json"
    output.write_text(json.dumps({"progress": saved,
                                  "clean_report": str(args.clean_report),
                                  "clean_report_sha256": hashlib.sha256((ROOT / args.clean_report).read_bytes()).hexdigest(),
                                  "replay_report": str(args.replay_report),
                                  "replay_report_sha256": hashlib.sha256((ROOT / args.replay_report).read_bytes()).hexdigest()},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Local delivery progress saved to PowerContext; official acceptance remains pending")


if __name__ == "__main__":
    asyncio.run(main())
