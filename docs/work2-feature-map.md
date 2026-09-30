# Work2 feature and data map

Scope: static inventory of the legacy Work schema at `535e74b6f7d5a7139bf524bbb290ca03b84a1cf7` and the Octop source tree at `232030f46c5450801ca87809f8a4da57aefc5a05`. This is a migration classification, not proof of production rows or a migration instruction. Real data counts and file contents were not read.

## Legacy Work tables

The tracked Drizzle schema contains 32 tables. The migration directory contains 35 tracked SQL files. The working repair branch also has uncommitted Feishu grant/disabled-outbox work; it is protected separately and is not part of the new Octop schema.

| Data class | Tables | Owner | Planned handling |
|---|---|---|---|
| Identity and organization | `users`, `phoneVerificationChallenges`, `organizations`, `organizationMembers`, `userIdentities`, `organizationRegistrationPolicies`, `organizationInvitations`, `identityReceiptConsumptions`, `accountSecurityEvents`, `accountSecurityRateLimits` | Work identity and membership | Preserve audit and membership history. Map accounts only through verified identity evidence; do not reuse old sessions or silently relink accounts. Live organization/admin recovery state is `UNKNOWN`. |
| Tool settings and budgets | `aiToolPreferences`, `workAiCallBudgets` | Work policy and budget ledger | Keep non-retired preferences. PixelRAG and Feishu remain disabled regardless of stored preference. Preserve attempt/counter history and the 20/task, 100/user/UTC-day, 500/org/UTC-day semantics; do not reset during migration. |
| Files and knowledge | `organizationResources`, `personalFiles`, `knowledgeCitations`, `knowledgeDeleteRequests`, `knowledgeSettings` | Work asset and knowledge service | Preserve local bytes, ACLs, versions, citations, and deletion requests. No PixelRAG index is presumed authoritative; do not delete or silently reimport external data. |
| Workspace and projects | `workspaces`, `organizationProjects`, `projectReviews` | Work project service | Preserve institution and project ownership, lifecycle, review snapshots, and audit linkage. |
| Conversations and tasks | `workThreads`, `workMessages`, `taskRuns`, `taskSteps`, `pendingActions` | Work execution and history | Retain history. Incomplete or uncertain actions must be blocked for review, never replayed as successful. |
| External action records | `workOutbox` | Work outbox owner; provider-specific policy at dispatch | Retain target, operation, and status. Stop new retired-provider work; queued and ambiguous writes require explicit blocked/uncertain handling. Do not repurpose generic outbox workers. |
| Audit and reusable work | `auditLogs`, `organizationSkills` | Work audit and skill catalog | Preserve audit records. Revalidate each skill's tool set against the disabled capability policy before activation. |
| Opportunity workflow | `organizationApplicationProfiles`, `opportunityApplications`, `opportunityReminderEvents` | Work opportunity service | Preserve existing application state, source links, and in-app reminder history. |
| Feishu state | `feishuConnections` | Work integration-retirement archive | Preserve historical connection metadata for controlled history/unbind workflows; it is never a live context source and must not issue token or business requests. |

## Runtime and external-write map

| Entry or dependency | Source-declared path | Data/write boundary and disposition | Owner |
|---|---|---|---|
| HTTP and WebSocket agent execution | `/api/agents/*`, `/api/agents/{id}/chat/ws` → `api/routers/agents.py`, chat routers → harness | Must stay private behind Work authorization; direct raw Octop access is not a user-facing Work boundary. Gate tools before execution. | Work gateway and runtime adapter |
| Scheduled prompts | `infra/cron/manager.py` / `CronJob` | In-process scheduler, not a separate queue. New Work schedules need an authorized context and dispatch policy; do not assume the generic cron worker is a Feishu queue. | Work runtime owner |
| IM ingress and bot setup | `infra/gateway/processor.py`, channel routes, bot creators | Feishu/Lark entrypoints are in scope for permanent retirement; non-Feishu channels require separate product authorization before exposure in Work. | Integration owner |
| MCP connectors and plugin tools | `infra/connectors/`, `infra/agents/plugins/`, `agent_tools.py` | External reads/writes must be explicitly approved and scoped; unknown tools default deny. Feishu CLI/OAuth/MCP paths must not be re-enabled by config or old grants. | Work security and integration owner |
| Model/provider requests | Harness provider runtime and configured provider credentials | Route through an approved proxy with per-attempt policy/budget checks; production endpoints and active keys were not inspected. | Work AI platform owner |
| Native CLI | `octop run`, connector CLI helpers, admin commands | Local filesystem/CLI access bypasses Work HTTP identity. Keep it operational-only and out of ordinary Work task execution; Feishu/Lark CLI commands are disabled for Work. | Release/operations owner |
| File downloads and browser extension | Work asset API and separate private browser extension | Keep local file ACL and download checks; extension remains a separate product and is not treated as an institution-wide Work identity. | Work assets / extension owner |
| Hub and Business MCP | Separate repositories and deployments | No source change is implied by the Octop fork inventory. Preserve separate data/permissions and continue their independent Feishu/Pixels retirement verification. | Hub and Business MCP owners |

The runtime map is based on the candidate source tree, not production routing. Process versions, configured credentials, active integrations, live write destinations, and the unique account-recovery path remain `UNKNOWN` pending authorized evidence.

The old source declares MariaDB/Drizzle and its deployment contract uses Node.js, a systemd service, a local health check, and versioned release directories. The new Octop source declares SQLite or PostgreSQL and a single-process runtime. Do not copy old MariaDB SQL into Octop. No production migration ledger, active rows, object-store inventory, or recovery-account mapping was accessible in this task.

## Octop capability surfaces found

- Feishu/Lark appears in the channel API, QR/bot creator, gateway channel and connector adapters, OAuth/user-auth routes, `feishu-cli`, and the `lark-oapi` dependency. The capability must be disabled at registration, API, CLI, scheduling, and egress boundaries; hiding a dashboard form is insufficient.
- PixelRAG has no source match in this Fork snapshot. It remains explicitly denied by the Work capability policy so a later upstream/plugin addition cannot enable it by default.
- Octop's architecture describes one process with FastAPI, WebSocket, cron scheduling, plugin loading, SQLite/PostgreSQL control-plane storage, and per-agent workspaces. It documents no separate external worker/outbox queue.
- Work's organization, project, file, history, permissions, and budget data remain owned by the Work layer; Octop user/agent/session records are execution identities only.
