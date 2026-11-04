import json
from pathlib import Path
import tempfile
import unittest

from sdd_context.config import read_env
from sdd_context.documents import load_manifest, read_documents


class ContextInputTests(unittest.TestCase):
    def test_reject_path_traversal(self):
        for invalid in ("../outside.md", "/outside.md", "specs/../outside.md", "specs\\a.md"):
            with self.subTest(path=invalid), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "project.json"
                path.write_text(json.dumps({"project_id": "test", "documents": [
                    {"path": invalid, "role": "spec"}]}))
                with self.assertRaises(ValueError):
                    load_manifest(path)

    def test_preserves_raw_line_endings_and_extracts_symbols(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = b"def example():\r\n    return 1\r\n"
            (root / "code.py").write_bytes(raw)
            doc = read_documents(root, {"documents": [{"path": "code.py", "role": "implementation"}]})[0]
            self.assertEqual(doc.content.encode(), raw)
            self.assertEqual(doc.metadata["symbols"], [{"name": "example", "line": 1, "end_line": 2}])

    def test_env_values_are_literal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("# comment\nSECRET='$(do-not-execute)'\nVALUE=x=y\n", encoding="utf-8")
            self.assertEqual(read_env(path), {"SECRET": "$(do-not-execute)", "VALUE": "x=y"})


if __name__ == "__main__":
    unittest.main()
