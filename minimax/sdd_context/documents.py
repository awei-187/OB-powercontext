import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

ROLES = ("spec", "implementation", "regression_test", "target_test")


@dataclass(frozen=True)
class Document:
    document_id: str
    path: str
    role: str
    sha256: str
    content: str
    metadata: dict


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object")
    project = manifest.get("project_id", "")
    if not isinstance(project, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project):
        raise ValueError("project_id must contain 1-64 letters, digits, underscores or hyphens")
    entries = manifest.get("documents")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Manifest must contain a nonempty documents list")
    paths = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "role"}:
            raise ValueError("Each document requires exactly path and role")
        if not isinstance(entry["role"], str) or entry["role"] not in ROLES:
            raise ValueError("Unknown document role")
        name = entry["path"]
        if not isinstance(name, str) or not name or "\\" in name:
            raise ValueError("Use relative POSIX document paths")
        parsed = Path(name)
        if parsed.is_absolute() or ".." in parsed.parts or parsed.as_posix() != name:
            raise ValueError("Document paths must be normalized and stay within project root")
        if name in paths:
            raise ValueError("Duplicate manifest document")
        paths.add(name)
    if set(x["role"] for x in entries) != set(ROLES):
        raise ValueError("Manifest must include specification, implementation and both test roles")
    return manifest


def read_documents(root: Path, manifest: dict) -> list[Document]:
    """Validate the complete input before starting any database changes."""
    documents = []
    for entry in manifest["documents"]:
        path = (root / entry["path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Document symlink escapes project root")
        data = path.read_bytes()
        if not data or len(data) > 2_000_000:
            raise ValueError(f"Document must contain 1..2000000 bytes: {entry['path']}")
        # Preserve original bytes through strict decoding/encoding, including CRLF.
        text = data.decode("utf-8")
        metadata = {"line_count": len(text.splitlines()), "symbols": [], "requirements": []}
        if path.suffix == ".py":
            tree = ast.parse(text, filename=entry["path"])
            metadata["symbols"] = [
                {"name": node.name, "line": node.lineno, "end_line": node.end_lineno}
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
        else:
            metadata["requirements"] = list(dict.fromkeys(re.findall(r"\b[A-Z][A-Z0-9_]*-\d+\b", text)))
            revision = re.search(r"\bRevision:\s*(\d+)\b", text)
            if revision:
                metadata["revision"] = int(revision.group(1))
        documents.append(Document(digest(entry["path"].encode()), entry["path"],
                                  entry["role"], digest(data), text, metadata))
    return documents
