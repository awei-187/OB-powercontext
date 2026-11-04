"""Source identity works in a Git checkout and in an exported delivery directory."""

import hashlib
from pathlib import Path
import subprocess


def source_identity(root: Path) -> dict:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = None
    paths = []
    for directory in ("sdd_context", "scripts", "sample_project", "tests"):
        paths.extend((root / directory).glob("*.py"))
    for directory in ("specs", "tasks"):
        paths.extend((root / directory).glob("*.md"))
    paths.extend(root / name for name in ("pyproject.toml", "uv.lock", "project.json", "compose.yaml"))
    return {"git_base_commit": commit,
            "source_identity": "SHA-256 identifies the actual delivered working files; Git metadata is optional",
            "working_tree_sha256": {
                str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(paths) if path.is_file()}}
