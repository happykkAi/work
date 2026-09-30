# Work2 Octop 替换续验进度（2026-09-28）

> 2026-09-30 当前状态覆盖：本地候选已封版，完整源摘要 48d2e47478b902fdfdf7af93f3815b93c94f38f48787b6e8fba763d6b9f63522；最终 make check-all 退出0（3930 passed / 21 skipped / 13 warnings），Dashboard 独立完整复跑1089 passed，真实PG/分发13 passed。PG重启500、空闲会话失效、task跨UTC日额度已修复并实跑；同runtime第二进程误阻断活跃任务、runtime策略/额度写权限和产品级迁移/业务/升级恢复仍阻断。下面为历史记录，不能当最终版本证据；详见 [固定范围验收](work2-fixed-scope-acceptance-2026-09-30.md)。不具备受控预发准入，生产未授权。

**范围：** P0/P1 本地门禁、P3a 最小身份链和 P2 实际执行验证。这是本地候选状态，不是替换完成、发布或生产验收报告。旧 Work、Hub 和 Business MCP 仍按各自仓库与发布边界管理。

> 2026-09-29：真实 PostgreSQL 文件当前 8/8 通过，Dashboard 实时 URL token 清理后为 207 个测试文件 / 1,089 passed，详见 [本地真实环境续验记录](work2-local-real-environment-acceptance-2026-09-29.md)。entry/A/B runtime 双容器和生产替换仍阻断。

## 结果摘要

| 阶段 | 状态 | 已有证据 | 未关闭项 |
| --- | --- | --- | --- |
| P0 基线、范围与止损 | **本地部分完成；生产盘点 BLOCKED** | Fork/上游/旧 Work 来源基线、代码级数据与调用面清单、UNKNOWN 缺失值保护和历史修复备份已记录。 | 没有只读生产通道；部署 SHA、迁移账本、机构/文件规模、容量、真实账号映射和管理员恢复路径仍为 UNKNOWN。 |
| P1 可复现构建与 Fork 治理 | **本地门禁通过；托管仓库治理未验收** | 最终本地完整门禁 3,903 通过、20 跳过、21 warnings；Dashboard 生产构建与 Octop/work_platform 包构建通过。 | GitHub 保护规则、Actions 权限、CI 和真实发布 SHA 未验证。 |
| P3a 最小身份、成员与运行映射 | **合成数据真实 PostgreSQL PASS；业务迁移仍 BLOCKED** | 专用 PostgreSQL 容器中完成初始化、真实 backup/restore、v3→v5 重复迁移、并发/重启防重放、撤权和额度竞争。 | 旧 Work 业务数据迁移、权限/关联对账、生产规模和 checkpoint-history 未验收。 |
| P2 实际执行与机构隔离 | **本机 A/B+mTLS 路由通过；物理隔离 BLOCKED** | 测试 CA 下入口以客户端证书访问 B，B 的服务端证书受校验并返回 WebSocket 帧，A 未收到请求；无客户端证书、不可信客户端证书和错误服务端 CA 均被拒绝。 | PostgreSQL、两个容器运行单元、独立角色/卷/凭据和受控出网未验收。 |

## 候选来源与基线

- 分支：work2/p0-p2-20260928；HEAD：9630df997c4d74dc49effae6102f96423b0059ff。这是合成快照提交，不是发布 SHA，也不包含全部未提交内容。
- 上游与 Fork 基线：232030f46c5450801ca87809f8a4da57aefc5a05；上游树 SHA：5aff5ae96c9ed92c21b5d5a97bd2bc7740f12f7d。
- 当前候选清单为 3,698 个常规文件，SHA-256 05234fd9449fc190c1ba0a90424a4069e5339a8ace497df1db7930806f82f168。逐文件清单见本地证据 work2-source-manifest-local-real-env-20260929.sha256；清单排除 symlink、进度/发布/续验文档与 ignored 产物、依赖缓存和证据目录。
- 工作树保持未提交。deploy/work/build-manifest.json 的 work_sha 仍为 null，没有把合成 HEAD 伪装成发布版本。

## P0 基线与遗留数据

- docs/work2-baseline.md、docs/work2-feature-map.md 和 tools/work/inventory.py 记录来源 SHA、旧 Work 静态表/迁移清单、Octop 路由与执行调用面、历史数据处置以及 Fork Actions 风险。旧 Work 未提交修复文件与摘要保存在 protected-old-worktree。
- tests/work_contracts/test_inventory.py 覆盖证据缺失时输出 UNKNOWN。32 张旧 Work 表和 35 个迁移文件是代码基线盘点，不代表生产行数或当前线上迁移状态。
- 没有生产只读渠道，因此线上 Work/worker SHA、迁移账本、机构数量、并发、数据量、最大对象、增量、数据库/对象存储容量和唯一管理员恢复路径均为 UNKNOWN。它们阻断容量与替换发布判断，不阻断合成代码开发。
- Octop 源码保留本地用户名/邮箱+密码登录路径。生产账号能否安全映射、管理员是否可恢复及浏览器登录持久化均未验证，不能据此迁移账号。

## P1 工具链与本轮门禁

- 目标工具链：Python 3.12.13、Node 24.21.0、npm 11.19.0、uv 0.12.19。此前两个 Python 锁定项目的 lock check 与临时干净环境安装、Octop/work_platform wheel 构建已通过。
- 最终完整门禁：`make check-all`，退出码 0，3,903 passed、20 skipped、21 warnings，342.18s。21 条 pytest warnings 为 16 次并行 worker 重复的 Lark SDK 弃用提示、4 条 websockets/uvicorn 提示和 1 条 discord `audioop` 弃用提示；不能与 ESLint 的 67 warnings 合并计数。
- Node 24.21.0 / npm 11.19.0 下 Dashboard：205 个测试文件、1,087 passed；make build 内 tsc 与生产构建通过，转换 9,356 个模块并生成 98 个 PWA precache 项。ESLint 0 errors、67 warnings，保留大 chunk 提示。
- 2026-09-28 完整 Dashboard 构建通过；Python 打包 fallback 使用标准隔离构建并成功生成 Octop wheel/sdist。work_platform wheel/sdist 也重建成功，分发合同 3/3 通过。产物保存在本地 candidate-build-final-notify-auth-20260928；四个 SHA-256 已同步到 deploy/work/build-manifest.json。当前源码此后已有 PostgreSQL 测试和实时 URL-token 改动，因此这些产物不匹配当前候选，`work_sha` 仍为 null。
- 本地完整门禁中的 20 项 skip：9 项需要 Linux root/bwrap，9 项需要 PostgreSQL（8 项 control-plane、1 项 checkpoint-history），1 项分发合同在完整门禁未传入 wheel 路径，1 项 AgentManager 测试因 HarnessAgentConfig monkeypatch 不兼容。分发合同另有独立构建验证，3/3 通过；2026-09-29 已直接实跑并关闭 8 项 PostgreSQL control-plane 场景，checkpoint-history、Linux sandbox 和 AgentManager case 仍未验证。必须由下一次完整门禁重新给出 skip 总数。
- 目标构建的 npm ci 提示 esbuild/fsevents 安装脚本未获 allowScripts 覆盖；构建仍成功。构建输出写到临时目录，仓库忽略的原有 Dashboard bundle 已校验恢复，dist 未被覆盖。

## P3a 最小可信身份链

- WorkControlPlane schema 已升至 v5：v3 新增 runtime endpoint/handoff secret，v4 新增持久化 handoff 消费记录，v5 在 run 中持久化 `connection_id`。统一入口只接收自身登录 token 和 agent_id，不接受客户端提交的 organization、runtime 或 endpoint；它从 Work control 数据库解析全局用户、active membership、组织策略和目标 binding。
- 入口为目标 runtime 签发最长 60 秒、默认 30 秒、带 runtime audience 的 HS256 handoff；A 的 secret/token 不能进入 B。目标 runtime 重新查询当前成员、机构、agent、binding 和本地 Octop 用户，再签发 60 秒本地会话；各 runtime 不共享 Octop JWT secret。
- 最终复核新增 fail-closed 断言：目录返回的 agent 必须等于请求 agent，grant organization 必须等于 binding organization。对应回归先观察到旧实现 2 项失败，再修正为 6/6 通过。
- Gateway 在排队后重新激活并校验 run；Harness 的 WorkExecutionMiddleware 在模型和工具调用前复查成员、策略和预算。Work 模式下 ProactiveCare 调度暂停、配置写入拒绝；/chat/polish 在创建模型前拒绝。
- `jti` 的首次占用使用带数据库时间条件的 `INSERT ... SELECT ... WHERE expires_at > now() ON CONFLICT DO NOTHING RETURNING`，并与当前身份、成员、策略、agent/binding 行锁复核处于同一事务；消费记录含 `connection_id`。2026-09-29 已在专用真实 PostgreSQL 中实跑并发一次性消费、进程重启后的重放拒绝和撤权失效；该证据不覆盖 entry/A/B 双容器或生产数据。

## P2 实际执行边界与隔离

- dispatch_external 的 fail-closed 检查已由 Harness WorkExecutionMiddleware 在模型和工具调用路径使用。完整 tests/integration/test_chat_ws.py 回归 27 passed，日志：本地证据 work2-p2-websocket-after-runtime-binding.log。
- 覆盖有权成员完成 loopback 模型/工具调用、访问另一机构资源被拒绝、模型步骤后撤权阻断下一工具、策略读取/预算失败不发模型请求、不确定工具写入不重试、缺 control-plane 拒绝，以及 Work 模式下 ProactiveCare 和 Prompt Polish 旁路拒绝。测试未连接真实供应商。
- 新增显式 `WORK_ENTRY_MODE=1`，避免把“没有本地 binding”误判为统一入口；机构 runtime 禁止入口代理模式。Dashboard 继续访问普通 `/api/agents/{agent_id}/chat/ws`，该 route 在入口模式下实际委托 `/api/work/v1/agents/{agent_id}/chat/ws`，再由入口按数据库 binding 选择目标并代理 WebSocket。
- 本机集成验收实际启动 A/B 两个 FastAPI/WebSocket runtime：入口选择 B，B 完成交接并返回帧，调用记录仅有 `handoff:runtime-b` 和 `websocket:runtime-b`；A 未收到请求。该结果证明固定实例的服务端选择和数据帧路径，不证明容器或 PostgreSQL 隔离。
- 新部署合同固定声明 work-entry、octop-org-a、octop-org-b；A/B 使用分离内部网络、卷、数据库 URL secret、handoff secret 和 mTLS 服务端材料，不暴露 runtime host port，也不挂 Docker socket。双 PostgreSQL 验收模板也已补齐 HTTPS endpoint、handoff 与 mTLS 启动合同。模板假定数据库/角色已预创建，不是实例自动创建、扩缩容或完整编排平台。
- handoff 校验 `purpose`、issuer、audience、时限、机构、runtime、agent、用户和 32 位十六进制 `connection_id`；连接标识贯穿入口、handoff、目标 WebSocket、run 上下文/记录和模型/工具 attempt 日志，可与 handoff 消费日志关联。目标 WSS access token 改由 `Authorization` header 传递；Dashboard chat、全局通知、browser、terminal 与 ADB 登录 token 使用 `octop.auth.<JWT>` WebSocket subprotocol，trajectory 使用带 `Authorization` header 的 fetch SSE；这些当前实时路径不再把登录 token 放入 URL/query。desktop/mobile stream token 原本就在首帧而非 URL；media stream 未发现当前 Dashboard URL-token 调用点。不记录 token/Cookie/正文。错误连接标识在消费前拒绝，不烧掉合法 handoff。
- 独立只读审阅前两轮共发现并已修复 2 项高影响和 6 项中等问题：真实 PostgreSQL 查询参数顺序、两份模板启动合同、目标 WSS query token、事务内到期复核、run/attempt 追踪关联、Dashboard 未实际进入统一入口、mTLS runtime 的明文 HTTP healthcheck、chat 登录 token 位于入口 WS query。第三轮又发现全局通知仍使用 query token及普通 route 贯穿证据缺口；通知已沿用 subprotocol 修复，A/B+mTLS 测试已改从普通 Dashboard route 进入。最终极窄独立复验确认这两项关闭，未新增 Critical/Important；独立审阅不是对真实 PostgreSQL 或容器环境的通过判定。
- 固定模板已改为 HTTPS/WSS mTLS：入口校验 runtime 服务端证书并提供客户端证书，runtime 要求可信客户端证书，不允许 HTTP endpoint、证书校验关闭、HTTP 回退或明文 companion listener；runtime healthcheck 使用无凭据的本机 TCP 监听探针，不读取证书私钥。本机真实 TLS 握手覆盖正确证书、缺客户端证书、不可信客户端证书和错误服务端 CA；这仍不是双容器/生产证书验收。
- 2026-09-29 启动现有 Colima 0.10.3 profile 且未重置；Docker Compose 5.3.1 可用。准确锁定的 pgvector/PostgreSQL 16 镜像已拉取，专用容器 `work2-pg-accept-20260929` 与独立卷 `work2_pg_accept_20260929` 保留，仅绑定 `127.0.0.1:55432`。
- 使用容器合成凭据设置 `OCTOP_TEST_DATABASE_URL` 后，当前 PostgreSQL 文件 8/8 通过，覆盖真实 backup/restore、v3→v5 重复迁移、并发/重启 handoff、防撤权和 40 路额度竞争。entry/A/B runtime 镜像未生成，物理隔离、实际角色/卷/secret 与受控出网仍阻断。
- P3a 的合成数据持久化授权场景已通过真实 PostgreSQL；旧 Work 业务迁移/对账与 P2 物理双机构隔离仍是替换发布阻断。本机 A/B 路由通过不能作为生产数据迁移依据。

## 续验补充（2026-09-28）

- Registry 复查：`https://registry-1.docker.io/v2/` 在 5 秒连接期限内超时；Colima profile 为 `Stopped`，默认 Docker socket `/var/run/docker.sock` 不存在。没有下载镜像、启动数据库或改用其他镜像/Registry。
- 浏览器续验已完成限定范围：用户授权后，在 Chrome 154 / macOS 15.7.8 的隔离临时 profile 加载社工助手 1.1.0 源码副本；Chrome 显示版本 1.1.0、扩展已启用，工具栏弹窗和设置页可打开，诊断显示 FutureSocial 未连接。
- 使用合成键 `codexSyntheticPersistenceProbe` 验证 `chrome.storage.local` 写入、读取、`chrome://restart` 后读回及删除；重启后的 `chrome://version` 仍指向临时 profile。未登录 FutureSocial、未触发收藏/下载/同步或外部写入。1.1.0 源码 Node 回归本轮重跑 42/42（Node 24.19.0）。
- 此浏览器验收只证明 1.1.0 弹窗与 Chrome 本地存储跨重启可用；未通过 Feishu 页面/外部请求观测验证 SEC-02 停用边界，独立的 Feishu 停用候选仍未在 Chrome 运行。DNS 解析规则阻断外部域名；没有把未观测的网络请求写成零请求结论。临时 profile 与源码副本已移入可恢复废纸篓，用户日常 Chrome 未操作。

## 保留、旧 Work 与权限边界

- PixelRAG 和飞书继续作为退役能力；不新增 CLI、OAuth、MCP 或替代通道。历史资料、外部表、连接审计、同步记录和本地文件保留。
- 旧 Work 冻结锁干净安装报告保存在本地 old-work-clean-install/summary.md：Node 22.13.0、pnpm 10.4.1、904 passed/11 skipped、类型/构建通过。迁移应用到一次性 MariaDB 11.4 合成库后，14 项集成测试及 SEC-02 的 0036 用例共 15 项通过；第一次空库测试因尚未应用迁移失败，随后在新临时库按迁移顺序重跑通过。社工助手扩展 Node 测试 42/42、语法、manifest 与 settings-dom 检查通过。
- 早先一次隔离 Chrome 尝试曾出现 `ERR_FILE_NOT_FOUND`，当次没有成功读写存储；后续对社工助手 1.1.0 源码副本的独立运行已通过弹窗加载和合成存储跨 `chrome://restart` 验收。该结果不覆盖 Feishu 停用候选的 Chrome 运行时，也不代表真实站点、账号或外部请求验收。
- 生产只读盘点、真实浏览器登录、PostgreSQL/MariaDB 对账、GitHub rules/CI、部署、迁移账本、线上生效均未完成。
- 本轮没有提交、推送、部署、生产迁移、生产配置改动、外部凭据撤销或生产数据删除。任何回滚仍须保持 PixelRAG 与飞书停用。
