# npm security audit - 2026-11-08

Command: `npm audit --json` with the locked dependency graph. Result: 5 high nodes, 0 critical. No `audit fix --force` was run and the lockfile was not silently upgraded.

## Dependency chains and use

| Audit node | Installed | Chain | Scope/use | Upstream fix indicated by npm |
| --- | --- | --- | --- | --- |
| `@huggingface/transformers` | 3.8.1 | direct production -> `sharp` | Browser bundle and local Worker inference; Node `sharp` path is not used by the text-only browser app | 4.3.2, semver-major |
| `sharp` | 0.34.5 | Transformers -> sharp | Node image processing dependency; not imported by application source or browser bundle | sharp 0.35.5, reachable through Transformers 4.3.2 per audit |
| `seekdb` | 1.4.0 | direct production -> optional native binding | Server mode uses the SDK mysql2 path; version is fixed to the tested seekdb 1.4 SQL/API | npm suggests 1.1.1 downgrade, semver-major/incompatible with this validation |
| `@seekdb/js-bindings` | 1.4.0 | optional dependency of seekdb -> `adm-zip` | Embedded-only native addon/download path; not loaded in `SEEKDB_HOST` server mode | npm suggests seekdb 1.1.1 downgrade |
| `adm-zip` | 0.5.18 | optional js-bindings -> adm-zip | Native binding archive handling; not executed in server mode | 0.6.1 exists, but it is outside js-bindings' declared `^0.5.16` range |

`npm audit --omit=optional --json` removes the seekdb native binding chain and reports 2 high nodes (`@huggingface/transformers`, `sharp`). This is an exposure analysis, not a claim that the default lockfile is clean.

## Advisories in the raw report

- sharp/libvips: [GHSA-f88m-g3jw-g9cj](https://github.com/advisories/GHSA-f88m-g3jw-g9cj), affected `<0.35.0`.
- sharp/libheif: [GHSA-rgj7-g3m4-5g8c](https://github.com/advisories/GHSA-rgj7-g3m4-5g8c), affected `<0.35.4`.
- sharp/librsvg: [GHSA-wq5f-xc86-pv6w](https://github.com/advisories/GHSA-wq5f-xc86-pv6w), affected `<0.35.5`.
- adm-zip memory allocation: [GHSA-xcpc-8h2w-3j85](https://github.com/advisories/GHSA-xcpc-8h2w-3j85), affected `<0.6.0`.
- adm-zip symlink overwrite: [GHSA-vwc7-r8mq-g2x9](https://github.com/advisories/GHSA-vwc7-r8mq-g2x9), affected `>=0.5.9 <=0.6.0`.
- adm-zip uncompressed-size allocation: [GHSA-7q85-xj36-vmfc](https://github.com/advisories/GHSA-7q85-xj36-vmfc), affected `<0.6.1`.
- adm-zip decompression-bomb bypass: [GHSA-rcw4-f5rp-g42v](https://github.com/advisories/GHSA-rcw4-f5rp-g42v), affected `<=0.6.0`.
- adm-zip SUID/SGID preservation: [GHSA-j5f4-cc29-5x44](https://github.com/advisories/GHSA-j5f4-cc29-5x44), affected `<=0.6.0`.
- adm-zip duplicate names: [GHSA-p634-w6r4-rjp2](https://github.com/advisories/GHSA-p634-w6r4-rjp2), affected `<=0.6.0`.
- adm-zip async size-guard bypass: [GHSA-c6fg-446q-cg94](https://github.com/advisories/GHSA-c6fg-446q-cg94), affected `<=0.6.0`.
- adm-zip async crash: [GHSA-8238-w5pm-2374](https://github.com/advisories/GHSA-8238-w5pm-2374), affected `<=0.6.0`.

## Decision

No compatible lockfile-only remediation exists within the declared ranges. Upgrading Transformers 3.x to 4.x requires browser bundle/API/model regression work and invalidates the submitted benchmark baseline. Downgrading seekdb to 1.1.1 conflicts with the required and tested 1.4 Server. Overriding adm-zip across an undeclared major range would only hide the audit node without validating the native downloader and is unnecessary for server mode.

For this submission, the operational mitigation is server mode: `SEEKDB_HOST` is mandatory, embedded bindings are not loaded, credentials are local-only, and the official database is bound to loopback. A future dependency branch should migrate Transformers to 4.3.2+ and take the next seekdb-js release that declares a patched archive dependency, then rerun the complete model/DB matrix before merging.
