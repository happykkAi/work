# Work2 delivery — 2026-09-30

## Provenance

Delivery branch: `release/work2-20260930`, based on actual remote main
`232030f46c5450801ca87809f8a4da57aefc5a05`, not the synthetic root commit.
The original candidate remains intact in its separate directory.
Pre-delivery tracked/untracked source archive SHA-256:
`6aced775fe529dd67e82215e8ac70e90fc6be8f8465601012d13e2f966a7486b`.

The first commit imports the previously validated Work2 candidate, not a release.
Historical manifests and acceptance reports describe their recorded candidates;
they are not evidence that this delivery branch or production has passed.
No private database exports, credentials, raw runtime logs or generated evidence
are included. `.superpowers/` is excluded from Git.

## Current authorization and gates

The user authorizes staged commits/pushes and a reviewed PR. Merge, preproduction
and production actions are conditional on their separate acceptance gates.
PixelRAG remains permanently disabled and Feishu remains closed.
No changes to the Hub site are in scope.

| Item | Status |
| --- | --- |
| Prior candidate imported and preserved | PASS |
| Multi-process active-run recovery | Focused real-PG PASS; final gates pending |
| Runtime policy/counter write boundary | Focused real-PG PASS; final gates pending |
| Legacy business migration/reconciliation | NOT_RUN |
| Browser institution/project/task/persistence/file flow | NOT_RUN |
| Version upgrade and two recovery scenarios | NOT_RUN |
| Final candidate full gates/review | NOT_RUN |
| Controlled preproduction | BLOCKED by above gates |
| Production switch | BLOCKED by above gates |

Existing deployment workflow is in `happykkAi/shegongai-agent-lab`
(`deploy-ucloud.yml`, production environment), with a separate production migration
workflow. It packages the old Node/Drizzle application; it is not yet a Work2
Python/PostgreSQL release contract. `happykkAi/work` has no configured Actions
secrets or environments at this read-only check. These facts must be reconciled
before deployment; the legacy workflow must not be invoked for Work2 as-is.

## Runtime ownership and authority repairs

Root cause A: startup unconditionally interrupted all queued/running tasks for
the runtime, including tasks owned by another live process. Schema 6 adds an
executor identity. An independent PostgreSQL session holds its ownership lock;
recovery interrupts only owners whose lock is gone. Owner fencing prevents an
old executor from completing another executor's run. Recovery does not retry
external actions. Terminal runs retain their status; abandoned reserved attempts
are recorded as uncertain without refund or automatic execution.

Root cause B: the old runtime database login could directly update policy and
quota tables. Schema 7 installs an immutable login-to-institution mapping,
read-only row-level access and constrained server-side business writes. The
offline migration owner provisions roles; a separate institution-scoped manager
can change allowed policy. Neither credential is mounted into a runtime.
Fixed task/user/organization limits remain 20 / UTC100 / UTC500.
The authority database is shared; Octop private databases, volumes and secrets
remain institution-specific. Direct table writes, target spoofing, retired
integration enabling and cross-institution manager writes are rejected.

The independent patch review found two additional reproducible boundary cases:
account/identity/binding revocation during quota-lock contention, and abandoned
attempts attached to already-terminal runs. Both failed against the pre-fix code;
authority-row locks and terminal-attempt recovery address these cases. Live
owners remain unaffected, and original terminal states remain unchanged.

Real dedicated PostgreSQL verification (2026-09-30):
`uv run python <temporary evidence runner> tests/integration/test_work_runtime_permissions.py tests/integration/test_postgresql_control_plane.py tests/unit/work -q --tb=short`
returned 0, **59 passed / 1 skipped**. The skip is the external pg_dump/restore
tool gate when its wrapper directory is absent; this run does not certify
business migration or backup restore. Strict type checking and final delivery
checkout verification are recorded separately, not inherited from this run.
No real provider or production data was used.

Delivery checkout rerun with the existing pg_dump/restore wrapper and the
historical Work distribution contract wheel: **77 passed, 45 subtests passed,
0 skipped**, exit 0 (8.89s). It includes real PostgreSQL checkpoints/history,
both runtime defects, Work unit tests and distribution/deployment contracts.
The contract wheel has unchanged Work-platform source; it is not claimed as the
new final Octop release artifact. Strict type checking of both changed domain
modules returned 0. The first delivery rerun failed three fixture-initialization
tests because their matching executor fixtures had not been transferred; those
fixtures and their executor assertions are now included, without lowering
production authorization or removing tests.

Evidence collection (local, not included in Git):
`/Users/happy/.codex/state/plugins/codex-security/scans/happykkAi-work-232030f/artifacts-6e0053d7477fd571829d6132eb3483bcb74d1cc03abe7868fb2095e6879de966/artifacts/20260930/`.
Red logs: `failures/runtime-revocation-race-red.log`, `failures/executor-terminal-red.log`.
Green log: `authority-review-fixes-green.log`.

The imported baseline is commit `a639ea4873cee8b99645974cfb07f49f67b5ec50`,
confirmed pushed; draft PR: https://github.com/happykkAi/work/pull/1.
Its actual local hook passed 3930 tests, with 53 skipped and 13 warnings;
that hook count is not the historical 21-skip full non-live gate.
Initial CI failed because dashboard dependencies were installed after lint,
and portable Python's fixed release URL disagreed with its fixed asset tag.
These pipeline failures are corrected without removing checks. A serial real
PostgreSQL CI job is added separately from the parallel unit gate.
The draft is not merge, preproduction or production approval.

## CI dependency and portable Python repair evidence

Commit `acb12fd57a43c6a3133a532500c23d57948c13eb` installs the locked
Dashboard dependencies before `make check-all`. It also aligns the portable
Python download release and asset tag at `20260807` (Python `3.12.13`).
Actual desktop run `36689054973` passed all four Darwin/Windows architecture
jobs. Work run `36689054956` passed its real PostgreSQL/multi-process job and
the full-stack gate, then failed in isolated contracts with exit 2: the separate
Work-platform development environment had not declared the YAML parser used
by the routing/isolation contract tests.

The same isolated command reproduced two `ModuleNotFoundError: yaml`
collection errors locally. The repair declares `pyyaml==6.0.3` in that project's
dev dependencies and updates its own lock; this is the version already locked
by Octop. No tests, assertions or gates are removed. The first offline lock
attempt could not resolve an uncached package; ordinary locked resolution
succeeded. Final isolated verification and downstream build results are recorded
against the new commit/CI run, not inherited from the failed run.
