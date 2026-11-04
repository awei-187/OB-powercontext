"""Real seekdb integration checks using disposable, isolated project identities."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from sdd_context.config import Settings
from sdd_context.documents import load_manifest, read_documents
from sdd_context.store import Store
from sdd_context.provenance import source_identity

ROOT = Path(__file__).resolve().parents[1]


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    run_id = uuid.uuid4().hex
    project = "verify-" + run_id
    other_project = "other-" + run_id
    store = Store(Settings.load(ROOT / ".env"))
    checks = []
    snapshots = []
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(), "project_id": project,
        "command": [sys.executable, "scripts/verify_context.py"], "python": sys.version,
        **source_identity(ROOT),
    }
    try:
        with tempfile.TemporaryDirectory(prefix="minimax-context-") as directory:
            root = Path(directory)
            manifest = load_manifest(ROOT / "project.json")
            manifest["project_id"] = project
            for entry in manifest["documents"]:
                destination = root / entry["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / entry["path"], destination)
            documents = read_documents(root, manifest)
            expected = {d.path: d for d in documents}
            store.ingest(project, documents)
            query = (ROOT / "tasks/order-status-filter.md").read_text(encoding="utf-8")
            result = store.prepare(project, query)
            check(result["ready_for_development"], "Required source role was not retrieved")
            check({s["path"] for s in result["sources"]} == set(expected), "Source set mismatch")
            for source in result["sources"]:
                doc = expected[source["path"]]
                check(source["content"] == doc.content, "Retrieved text differs from original")
                check(source["content_sha256"] == doc.sha256, "Citation digest mismatch")
                check(source["score"] > 0, "Expected a positive database fulltext score")
            snapshots.append(result)
            checks.append("All four source roles retrieved from real seekdb with exact text and digests")

            # prepare() must keep working when the original files are unavailable.
            spec_path = root / "specs/orders-v1.md"
            original_spec = spec_path.read_bytes()
            spec_path.unlink()
            from_database = store.prepare(project, query)
            check(from_database["sources"] == result["sources"], "Query depended on local source files")
            spec_path.write_bytes(original_spec)
            checks.append("Retrieval reads persisted database text, not local file contents")

            unchanged = store.ingest(project, read_documents(root, manifest))
            check(unchanged["changed"] == 0, "Unchanged re-import must not create document changes")
            checks.append("Unchanged re-import preserves document identities")

            original = original_spec.decode("utf-8")
            updated = original.replace("Revision: 1.", "Revision: 2.").replace(
                "`cancelled`. Reject", "`cancelled`, and `refunded`. Reject")
            check(updated != original and "refunded" in updated, "Update fixture did not change")
            spec_path.write_bytes(updated.encode("utf-8"))
            update_result = store.ingest(project, read_documents(root, manifest))
            check(update_result["changed"] == 1, "Only the spec should change")
            after = store.prepare(project, query)
            spec = next(s for s in after["sources"] if s["role"] == "spec")
            check(spec["metadata"]["revision"] == 2 and "refunded" in spec["content"],
                  "Revised specification is not effective")
            check(spec["content"] == updated and "Revision: 1." not in spec["content"],
                  "Outdated specification was returned as current")
            old = store.execute(
                "SELECT content FROM sdd_document_versions WHERE project_id=%s "
                "AND document_id=%s AND content_sha256=%s",
                (project, spec["document_id"], hashlib.sha256(original_spec).hexdigest()))
            check(len(old) == 1 and old[0]["content"] == original, "Historical source was lost")
            snapshots.append(after)
            checks.append("Revision 2 replaces current spec while revision 1 remains exactly auditable")

            # Invalid input must be detected before changing any current documents.
            spec_path.write_bytes(b"\xffinvalid utf8")
            try:
                read_documents(root, manifest)
            except UnicodeDecodeError:
                pass
            else:
                raise AssertionError("Invalid UTF-8 was accepted")
            check(store.prepare(project, query)["generation"] == after["generation"],
                  "Rejected import changed current generation")
            checks.append("Invalid input does not advance the imported generation")

            store.ingest(other_project, documents)
            isolated = store.prepare(other_project, query)
            other_spec = next(s for s in isolated["sources"] if s["role"] == "spec")
            check(other_spec["metadata"]["revision"] == 1, "Project isolation failed")
            checks.append("Project namespaces do not leak revised documents into another project")

            miss = store.prepare(project, "zzzxqnomatchingterm927462")
            check(not miss["ready_for_development"] and not miss["sources"],
                  "Unrelated query must not silently return a canned source set")
            checks.append("Unmatched query reports missing roles instead of fixed answers")

            # Verify explicit manifest deletion deactivates a current source without erasing history.
            extended = documents + [type(documents[0])(
                "a" * 64, "specs/additional.md", "spec", documents[0].sha256,
                documents[0].content, documents[0].metadata)]
            store.ingest(other_project, extended)
            removed = store.ingest(other_project, documents)
            check(removed["removed"] == 1, "Removed manifest source remained active")
            checks.append("Removed manifest sources leave current retrieval but retain history")

        report.update({"passed": True, "checks": checks, "contexts": snapshots})
    except Exception as exc:
        report.update({"passed": False, "checks": checks, "failure_type": type(exc).__name__})
        raise
    finally:
        # Only delete rows created under this run's unique project IDs.
        try:
            for namespace in (project, other_project):
                for table in ("sdd_documents", "sdd_document_versions", "sdd_projects"):
                    store.execute(f"DELETE FROM {table} WHERE project_id=%s", (namespace,))
        finally:
            report["queries"] = store.queries
            store.close()
            output = ROOT / "evidence" / "context"
            output.mkdir(parents=True, exist_ok=True)
            path = output / f"verification-{run_id}.json"
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"passed": report["passed"], "checks": checks,
                              "report": str(path.relative_to(ROOT))}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
