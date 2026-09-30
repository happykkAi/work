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
| Multi-process active-run recovery | FAIL in imported baseline; repair in progress |
| Runtime policy/counter write boundary | FAIL in imported baseline; repair in progress |
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
