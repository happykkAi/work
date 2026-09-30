# Work patches on the Octop base

Base source: `TencentCloud/Octop` / `happykkAi/work` at `232030f46c5450801ca87809f8a4da57aefc5a05`.

| Area | Local change | Reason |
|---|---|---|
| Runtime pins | Pin Python 3.12.13, Node 24.21.0, npm 11.19.0, uv 0.12.19 and the Node/Python image digests. | Reproduce the selected Work build target. |
| Fork workflows | Restrict inherited release, tag, image, FnOS, issue-write and branch-sync jobs to `TencentCloud/Octop`; lower workflow defaults to read-only and grant writes only to guarded jobs. | Prevent upstream publishing and repository writes from the Work fork. |
| Work package | Add the independently locked `work_platform` package, distribution verifier, and two-source build report. | Keep the new Work boundary in the wheel and trace both source SHAs. |
| Execution seam | Add a server-context value, organization runtime resolver, and a fail-closed capability dispatcher. | Establish the first tested integration contract before wiring Work identity and runtime calls. |

The current middleware/HTTP/WebSocket/cron/MCP/CLI paths are not all wired through the Work dispatcher yet. The Work image has no public ports and the runtime template places each synthetic unit on its own internal network, but production isolation and direct-API behavior remain `BLOCKED` until the adapter is wired to every executable path and two local containers are verified.
