# Work2 baseline

Baseline captured 2026-09-28 from GitHub metadata and an exact source archive. Production was not accessed.

## Source identity

| Repository | Ref | SHA | Result |
|---|---|---|---|
| `happykkAi/work` | `main` | `232030f46c5450801ca87809f8a4da57aefc5a05` | exact Fork baseline |
| `TencentCloud/Octop` | `main` | `232030f46c5450801ca87809f8a4da57aefc5a05` | identical to Fork baseline |
| `happykkAi/shegongai-agent-lab` | `main` | `535e74b6f7d5a7139bf524bbb290ca03b84a1cf7` | legacy Work baseline |

The Fork and upstream currently have no source delta at their default branches. The isolated candidate at `work2/p0-p2-20260928` was verified against all 3,649 GitHub blob/gitlink paths and the upstream tree SHA `5aff5ae96c9ed92c21b5d5a97bd2bc7740f12f7d`. Git smart HTTP did not return refs in this environment, so the local root commit is a clearly identified snapshot commit, not the upstream commit or a push-ready branch. No old Node/MariaDB source or SQL was copied into it.

The current candidate remains a dirty, uncommitted local checkout on a working branch, not a Git linked worktree. Its `HEAD` (`9630df997c4d74dc49effae6102f96423b0059ff`) is a synthetic snapshot identity; it does not identify all working-tree contents and must not be used as a release SHA. See `docs/work2-progress-2026-09-28.md` for the current file-manifest digest and P0–P2 evidence. The candidate manifest deliberately keeps `work_sha` null until a real reviewed source revision exists.

## Existing local repairs

The legacy Work checkout is on `fix/cross-system-retirement-20260927` at the legacy Work SHA with 95 changed files. Its tracked diff, untracked files, and file hashes are preserved in `/Users/happy/Documents/Codex/2026-09-28/work2-octop/protected-old-worktree`. The checkout was not modified during baseline capture. The repair evidence is local only; it does not establish a production release.

## Source-declared runtime and build state

- Octop `mise.toml` declares Python `3.12`, Node `20`, npm `10`, and floating `uv = latest`. Its release and Docker frontend stages use Node 20; its desktop workflow uses Node 24. These are source declarations, not production observations.
- Legacy Work CI and its systemd service contract use Node 22. The plan's prior Node 26.5 test observation is not runtime-aligned with that contract.
- This host reports Python 3.12.13, Node 26.5.0, npm 11.17.0, and Docker 29.6.2. `uv` and `mise` are not installed; Colima is stopped. These are local tools only.
- The Fork's `uv.lock` and `dashboard/package-lock.json` exist; their SHA256 values are in `deploy/work/source-manifest.example.json`. The Dockerfiles use floating `python:3.12-slim` and `node:20-slim` tags.
- The replacement build target will pin exact Python and Node patches, package-manager versions, lockfiles, and container image digests in P1. The source currently has no complete immutable image/runtime manifest.

## Production evidence

The inventory tool emits `UNKNOWN` for every missing production field. The following remain `UNKNOWN`: deployed frontend/API/worker SHA; migration ledger; institution count; active concurrency; total and largest file sizes; recent growth; compute/storage capacity; unique administrator recovery path; and actual database/object-store state. No authorized read-only production channel was available, so capacity and release decisions remain blocked.

The following report was generated from an empty, synthetic evidence object with `tools/work/inventory.py`; it is not a production query:

| Evidence | Value |
|---|---|
| Application/API/worker SHA | `UNKNOWN` |
| Migration ledger | `UNKNOWN` |
| Institution count and active concurrency | `UNKNOWN` |
| Total data, largest object, recent growth | `UNKNOWN` |
| CPU, memory, storage capacity | `UNKNOWN` |
| Administrator recovery path verification | `UNKNOWN` |

Source review confirms Octop has a mounted username/email + local password login path independent of Feishu SSO. This proves only that a non-Feishu code path exists; it does not establish migrated production accounts, identity mappings, an operational administrator recovery path, or browser login acceptance. Those remain release gates.

## GitHub Fork governance

Read-only GitHub API checks found only the `main` branch, no branch-protection rule (`HTTP 404: Branch not protected`), no configured environment, and Actions enabled with `allowed_actions=all` and no required action SHA pinning. No repository settings were changed. The inherited release, tag, GHCR, PyPI, desktop, FnOS, and main-to-develop write workflows require local Fork guards before a candidate can be treated as release-safe. Changing branch protection or Actions settings remains an external write requiring separate authorization.

## Spec and limits

The referenced companion file `../specs/2026-09-27-work2-replacement-design.md` was not found. This combined attachment contains the design section used as the P0–P2 spec. Static counts and source declarations are not production evidence; no data, credentials, migration, or deployment action was performed.
