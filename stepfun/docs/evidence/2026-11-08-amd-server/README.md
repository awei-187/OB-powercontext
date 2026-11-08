# 2026-11-08 AMD + seekdb Server evidence

This directory is the submission-safe archive of the real AMD laboratory run. It contains no database credentials, model files, browser profile, Docker volume, or precomputed result playback.

- `server-environment.json`: fixed image/tag/digests, server version, loopback binding, volume and limits.
- `db-server-probe.json`: direct `SELECT 1`, `VERSION()`, database/account and table count using the project `.env`.
- `browser.json` / `browser-edge.json`: 100-document end-to-end UI tests and state checks.
- `browser-attempt1-failed.json`: preserved first server-mode failure before the CTE transport compatibility fix.
- `fallback.json`: WebGPU-unavailable and FP16-init-failure routes, both ending in real seekdb retrieval.
- `persistence-ui.json`: application/container restart persistence verification.
- `storage-inspection.json`: persisted original text, metadata, 512-D vectors and table/index schema.
- `hybrid-sql-sample.json`: exact parameterized quality-v2 CTE with the vector value redacted, plus server version.
- `benchmark.json`: four precision/backend benchmark matrix.
- `quality.json`: five retrieval strategies with fresh browser-generated FP16 vectors.
- `model-matrix.json` / `model-matrix-edge.json`: preserved AMD Chrome/Edge model matrix.
- `npm-audit.json`: unmodified default npm audit report (5 high nodes).
- `SHA256.json`: file integrity manifest.

The full 7.7 MB local SQL trace remains under the ignored timestamped `test-results` directory because it repeats 512-D vectors. The representative SQL here retains the exact statement and transport while redacting only the vector parameter.
