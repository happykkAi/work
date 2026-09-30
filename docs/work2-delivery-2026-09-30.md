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
| Legacy business migration/reconciliation | Data-preservation rehearsal PASS; activation NOT_RUN |
| Browser institution/project/task/persistence/file flow | NOT_RUN |
| Version upgrade and two recovery scenarios | NOT_RUN |
| Final candidate full gates/review | Previous pushed SHA checked; new review repairs require final gates |
| Controlled preproduction | BLOCKED by above gates |
| Production switch | BLOCKED by above gates |

Existing deployment workflow is in `happykkAi/shegongai-agent-lab`
(`deploy-ucloud.yml`, production environment), with a separate production migration
workflow. It packages the old Node/Drizzle application; it is not a Work2
Python/PostgreSQL release contract. GitHub environments `work2-preproduction`
and `work2-production` were subsequently created in `happykkAi/work`; they have
no protection rules, branch policy or configured deployment credentials. No
Work2 deployment workflow or server activation contract has been installed.
Empty environments are not release approval. The legacy workflow must not be
invoked for Work2 as-is.

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

Local isolated contracts with the newly built Work wheel returned exit 0:
**16 passed, 45 subtests passed, no skipped**. `uv lock --project
packages/work_platform --check` returned 0; the real pre-commit hook completed
its static, change-aware tests and Dashboard build. Repair commit
`8c31b7b344eef7cd2d2d436cda61fac5f7f42278` is pushed and read back from GitHub.
Work CI run `36691825423` is the new candidate run; do not mark it passed while
it is still running.

The old skipped default-model forwarding test is restored without changing its
assertions. Its fake configuration was not a dataclass, so security policy
application failed; the test also had not registered its pinned model. A spy
now invokes the real configuration constructor, with the synthetic model
registered locally (no model call). Removing the skip first reproduced the
TypeError, then the missing-provider assertion; corrected test fixtures and the
entire agent-manager file returned **95 passed**, exit 0. Evidence:
`.superpowers/delivery/agent-manager-unskipped-final.log`.

## Legacy data-preservation rehearsal (not activation)

The offline owner-only import validates an explicit table catalog, identifiers,
relationships, institution/member states, integer quota usage and historical
attempt identifiers before destination writes. Original object byte hashes and
parsed-text hashes are verified separately; copying verifies the resulting bytes.
Unknown tables, invalid relationships/states and corrupt or missing files fail
explicitly. Pending actions, outbox and old tasks remain non-executable history;
live tokens/verification/invitations are invalidated, not restored.

Each historical object has a durable checkpoint. A fixed synthetic snapshot
rehearses interruption/resume and repeated import. Existing authority users,
memberships and counters must match exactly; conflicting state fails and rolls
back the authority transaction, without overwriting access or consumed quota.
The three conflict scenarios first failed to reject on real PostgreSQL. Reimport
of a tampered stored record also first failed; comparison now includes the actual
stored payload, not only its digest column.

Provisioning no longer grants SELECT automatically to every `work_%` table.
Only the existing RLS read contract is allowlisted; new historical/private
business tables remain inaccessible to runtime roles. A real restricted-role
test proves a private record from another institution cannot be read, while
legitimate runtime and scoped manager operations still succeed.

This phase returns `IMPORTED_NOT_ACTIVATED`. Identity mapping, accessible migrated
sessions/files, project business activation, actual MariaDB source export and
browser acceptance remain **NOT_RUN**, not PASS. No production data or database
was used. Dedicated PostgreSQL evidence:
`candidate/happykkAi-work-232030f/.superpowers/sdd/Work2_Octop_完整替换与持续升级计划_20260927/real-env-20260930/legacy-authority-conflicts-red-valid-fixture.log`,
`.superpowers/delivery/legacy-reimport-tamper-red.log`
and `.superpowers/delivery/legacy-preservation-and-permission-final.log`.
The combined local import/unit/role gate returned **15 passed**, exit 0, no
skipped; Ruff and strict Work-platform mypy returned 0. The serial CI PostgreSQL
job now includes this import rehearsal.

## Target-platform build contract

The Work CI release build now uses the existing Dockerfile and locked
dependencies for `linux/amd64`, the observed production host architecture. It
does not publish or deploy. The checked GitHub SHA is an image label; an isolated
no-network import/dependency smoke test precedes image export. Wheel/sdist,
source manifest, image identity and SHA-256 sums are retained as a CI artifact.
PR builds identify their checked merge commit, not a falsely claimed final main
commit. Manual dispatch allows the same gate to verify the actual merged main
commit later. The pipeline ordering and portable Python release/tag also have
regression contracts. Image construction/run and CI upload remain pending until
their actual step results; a passing YAML contract is not an image acceptance.

## Checked delivery baseline and subsequent review repairs

For pushed source `0eedc803b24c6b09d0432bf882e540bd91eccb72`:

- Local `make check-all PYTEST_JOBS=4`: exit 0, 3944 passed / 25 skipped /
  13 warnings (452.61s), `.superpowers/delivery/check-all-0eedc80.log`.
- Dashboard: exit 0, 1089 passed / 207 files (100.61s), separate suite; not
  included in 3944. `.superpowers/delivery/dashboard-0eedc80.log`.
- Real PostgreSQL, multi-process, native backup/restore and distribution:
  exit 0, 94 passed / 46 subtests / 0 skipped (10.25s),
  `.superpowers/delivery/postgresql-contracts-0eedc80.log`.
- Work CI `36694198821` passed, including its real PostgreSQL job, isolated
  contracts, Dashboard, x86_64 image build, no-network import/dependency check,
  image export and artifact retention. Desktop `36694198770` and CodeQL
  `36694198803` passed. Linux standard CI passed; Windows in `36694198779`
  failed 2 / passed 3842 / skipped 125 (2144.01s).

The full-gate 25 skips are 9 platform-specific cases (3 `/root`, 6 Linux/bwrap),
15 PostgreSQL cases lacking the URL in the parallel gate, and 1 independent
Work-wheel case lacking the artifact variable. The latter 16 were executed in
the serial real-database/distribution gate; this does not turn the full gate
into a single zero-skip run. Evidence: `skip-reasons-0eedc80.log`.
The 13 Python warnings comprise 8 Lark SDK UTC/event-loop deprecations,
4 websockets/uvicorn deprecations and 1 Discord audioop deprecation. Frontend
ESLint warnings and jsdom/Vite diagnostics are separate, not declared harmless
solely because their exit code is zero.

Independent review of `232030f..0eedc80` found two Important issues:

1. Ordinary authenticated knowledge indexing and voice could call remote
   models without a Work execution context, policy or quota check. Actual
   JWT/router/background/adapter reproductions with transport-only stubs
   returned 201/200 and one outbound stub call each, without control checks.
   Work now rejects remote embedding/OCR and server voice at shared domain
   boundaries, including voice probes. Startup retains remote embedding jobs;
   with remote OCR configured it retains images/PDFs without resetting their
   state while continuing local document indexing. No remote-to-local fallback
   is introduced. Standalone Octop and local parsing/storage remain available.
   The original negative tests failed before repair. Final focused regression:
   179 passed, exit 0; strict mypy passed. This includes real authenticated HTTP
   403 results for ordinary knowledge/STT/TTS requests, zero model transport
   calls, and local document controls. Security evidence is in the standalone
   Codex Security collection for this delivery directory (`optional-models-*`).
2. Root Octop wheel and desktop packages omitted required `work_platform`;
   pytest's source path and Docker's separate install masked startup failure.
   The root wheel and sdist now include those modules from their existing
   source tree. Portable and target-image smoke checks import the actual
   server and launch modules. A built wheel extracted into an isolated directory
   now imports startup with no source-tree path or extra Work installation.
   This artifact test first failed on missing Work modules and then passed.

The Windows failures are not skips: the ADB authentication test incorrectly
relied on the host being POSIX, and the workflow reader relied on the Windows
default cp1252 encoding. The test now uses an isolated POSIX selector for its
authentication-only path (no PTY/process), and workflow reads explicitly use
UTF-8. The original assertions remain. Focused local verification: 6 passed /
42 subtests, exit 0. Real Windows verification remains pending for the new SHA.

The repeated `retiredFeatures` locale objects are removed without changing
their retained text. CodeRabbit did not complete: its free-plan whole-diff
limit rejected 192 files (150 maximum), exit 1; no plan purchase or fabricated
review result. The separate independent review is not a CodeRabbit result.

These changes supersede the historical `deploy/work/build-manifest.json`;
that file is explicitly marked historical, not a current release identity.
Final source-bound checks/artifacts must be regenerated after these commits.
Legacy import still returns `IMPORTED_NOT_ACTIVATED`; project/member identity
activation, migrated history/files in the UI, the promised project/result/review
flow, actual MariaDB source conversion, version upgrade and both business
recovery scenarios remain unimplemented or NOT_RUN. They are product/code
gaps, not external-credential excuses. Preproduction/production gates remain
closed. No merge, preproduction or production operation has occurred.

## Upload and handoff scope

The latest user instruction is to upload the current work to GitHub and deliver
a handoff document; do not work on FnOS or continue server deployment in this
handoff turn. The earlier choice of an independent test entry, with old Work
untouched, remains recorded but no such entry was deployed.

Security repair `4a824eadeab9f91c006b57786bd63bef9f8eeb24` is pushed.
Distribution/Windows repair `5d37e33e8b87bab42a522e66b6d7e279f29aa03d`
has fresh focused verification: 7 passed / 42 subtests, exit 0, including the
actual built wheel/sdist startup check. Its required local hook passed static
checks, 4 change-aware tests / 2 deselected, and Dashboard build; it is not a
final full gate. Evidence: `.superpowers/delivery/distribution-windows-final.log`
and `.superpowers/delivery/distribution-commit.log`.

Read-only server checks found x86_64, Docker 29.1.3, no `docker compose` or
`docker-compose`, no `/etc/work2` or `/opt/work2`, approximately 1.6 GiB available
RAM and 6.2 GiB free disk at the check. Existing services/data were not changed.
No server keys were copied into GitHub, no production exports were taken, and
no DNS or Hub changes were made. See `docs/work2-handoff-2026-09-30.md` for
the handoff, evidence boundaries and continuation commands.
