# Work2 与旧 Work 候选交付状态（2026-09-28）

> 2026-09-30 发布准备结论：当前本地候选已冻结并完成同候选构建/门禁，不等于替换验收全部通过。受控预发 BLOCKED；生产替换 BLOCKED / NOT_AUTHORIZED。两项实测FAIL为第二runtime工作进程启动误杀活跃run、runtime仍能UPDATE策略/额度表；旧Work转换对账、机构资料→任务→成果→复核→导出及软件升级/两类恢复均缺实现或演练工具。最终证据、完整源/产物摘要和逐项skip/warnings见 [固定范围验收](work2-fixed-scope-acceptance-2026-09-30.md)。下文旧构建和计数已被覆盖，不可拼接放行。

本说明把代码实现、可执行测试、候选构建、部署和线上验收分开记录。**当前没有可发布的 Work2 替换版本；本地候选包不是生产发布包。** 未提交、推送、部署、迁移生产数据、改生产配置或撤销外部凭据。

> 2026-09-29 续验：锁定 PostgreSQL 镜像已拉取并在保留卷的专用容器中实跑；当前 PostgreSQL 文件 8/8 通过，Dashboard 当前实时 URL token 已清理。entry/A/B runtime 双容器、角色/卷/secret/egress、旧 Work 数据迁移、跨版本升级/恢复和业务闭环仍阻断。完整命令、失败边界和状态见 [本地真实环境续验记录](work2-local-real-environment-acceptance-2026-09-29.md)。`work_sha` 继续为 `null`。

## 问题闭环表

| 项目 | 本地处理与证据 | 当前状态与发布影响 |
| --- | --- | --- |
| 旧 Work SEC-01 PixelRAG 退役 | 旧 Work、Hub 与 Business MCP 的本地停用代码和回归记录见 [旧 Work 闭环表](../../../../../../ChatGPT/向阳花Ai/repairs/PixelRAG-permanent-retirement-20260927/work/docs/repair-closure-2026-09-27.md)。 | 本地实现已记录；生产状态未知，未发布。 |
| 旧 Work SEC-02 飞书整体停用 | 旧 Work、Hub、Business MCP、浏览器插件的本地入口/调用停用与合成测试在旧 Work 台账中分别记录。历史数据、审计和本地已导入资料保留；没有真实飞书读写。 | 线上生效、生产队列和配置未知。待授权清理生产配置及核实/撤销专用凭据；共享凭据不触碰。 |
| Work2 P3a 可信身份和成员解析 | schema v4 已加入 PostgreSQL 原子 `jti` 消费，schema v5 将 `connection_id` 持久化到 run；2026-09-29 专用真实 PostgreSQL 容器中完成 v3→v5 重复迁移、并发一次性消费、重启拒绝、撤权和额度竞争。 | 真实旧 Work 数据迁移与对账、checkpoint-history、生产规模和生产恢复仍未验收；P3a 只在合成数据范围内关闭。 |
| Work2 P2 实际模型/工具执行 | 单 runtime 27 项回归继续通过；固定 A/B 本机 mTLS 运行验收中入口只选择 B，B 完成交接及 WebSocket 返回，A 未收到请求。 | 不能证明 PostgreSQL、双容器、角色/卷/secret 或真实受控出网。 |
| Work2 双机构运行隔离 | 固定模板使用 HTTPS/WSS mTLS、分离网络/卷/数据库 URL/handoff secret，不暴露 runtime host port，不挂 Docker socket；拒绝缺失/不可信客户端证书和错误服务端 CA。锁定 PostgreSQL 容器已可用。 | entry/A/B Octop 镜像仍未构建成功；数据库角色权限、卷挂载、凭据消费和受控 egress 未验收。 |
| P0/P1 与旧 Work 干净安装 | 最终 Work2 完整门禁 3,903 passed / 20 skipped / 21 warnings；Dashboard 与 Python 包构建通过；work_platform 分发合同 3/3 通过。旧 Work 冻结锁干净安装报告继续作为归档证据。 | GitHub 规则/CI、Feishu 停用候选的 Chrome 运行时、生产 SHA/迁移账本和真实浏览器业务验收未完成。 |

## Work2 候选更新说明（未发布）

- 将 Work2 工作顺序明确为 P0/P1 本地准备 → P3a 最小身份与成员映射 → P2 实际执行/隔离 → 剩余 P3。
- 服务端身份解析与 Work run 上下文已连接 WebSocket、Gateway 和 Harness 模型/工具中间件；Work 模式下 ProactiveCare 调度和 Prompt Polish 执行被拒绝，避免未经授权的旁路。
- 新增显式 `WORK_ENTRY_MODE=1`、统一入口 WebSocket 和目标 runtime handoff。客户端不能选择 organization/runtime/endpoint；每个 runtime 使用独立 handoff secret 和独立 Octop JWT secret，目标实例重新查询当前授权。
- handoff token 默认 30 秒、最长 60 秒，校验 purpose/issuer/audience/时限及目标机构、runtime、agent、用户；PostgreSQL 唯一键和数据库时间条件负责一次性消费。`connection_id` 贯穿入口、handoff、目标 WebSocket、run 与 attempt 日志。当前 Dashboard 的 chat、全局通知、browser、terminal、ADB 均使用 `octop.auth.<JWT>` WebSocket subprotocol，trajectory 使用带 Authorization header 的 fetch SSE；这些当前路径不再把登录 token 放入 URL/query。desktop/mobile stream 的 token 在首帧而非 URL。固定模板使用 mTLS 且无 HTTP 回退，但双容器尚未验收。
- PixelRAG 与飞书保持停用，未新增 CLI、OAuth、MCP 或替代接入。历史资料和记录保留，不以旧缓存冒充实时来源。
- Work 模式的新增执行路径要求有效成员、当前策略与可用预算；专用真实 PostgreSQL 已验证持久化撤权、进程重启后的重放拒绝和额度并发。entry/A/B 双容器及物理双机构隔离仍未验证。
- 受影响能力：Work 模式下 ProactiveCare 和 Prompt Polish 暂不可用；机构聊天只在有效 Work execution context 下运行。双机构数据库/文件/秘密隔离尚未交付，不能用于承载生产机构数据。

## 修改后验证与候选构建

- 候选 HEAD：9630df997c4d74dc49effae6102f96423b0059ff，分支 work2/p0-p2-20260928；实际候选 checkout 含未提交修改。当前 3,698 个常规文件的清单摘要为 05234fd9449fc190c1ba0a90424a4069e5339a8ace497df1db7930806f82f168；逐文件 SHA-256 在本地 .superpowers/sdd/Work2_Octop_完整替换与持续升级计划_20260927/work2-source-manifest-local-real-env-20260929.sha256。
- `make check-all`：Python 3.12.13，退出码 0，3,903 passed、20 skipped、21 warnings，342.18s；跳过原因与警告分解见进度台账。
- Node 24.21.0 / npm 11.19.0：Dashboard 205 个测试文件、1,087 passed；类型检查及生产构建通过。ESLint 0 errors、67 warnings；Vite 保留大 chunk 提示。
- 2026-09-28 带锁定 uv 的完整 make build 退出码 0；当时重建 Octop 与 work_platform，分发合同 3/3 通过。产物位于本地 candidate-build-final-notify-auth-20260928，但不包含 2026-09-29 的 PostgreSQL 验收测试和实时 URL-token 清理，不能作为当前候选发布包。SHA-256：
  - Octop wheel：caab1ee9e83ba51a31240c7f83b8de291d73b53acdaa155dc0bec023d5b8fae3
  - Octop sdist：55d239ed05f15561acd0a9b348b7fd695fd2cedc1d6d4d931e9cb8a506c406be
  - work_platform wheel：28fa94e99daa088b0c177058dd3ad4d8e5ee2fe4a6190ed7b6b995ba4fcc0bac
  - work_platform sdist：671122b3552bdde84235b73ac4e3591e6541e6d19497f07c056410fb0052db15
- 独立只读审阅前两轮发现的 8 项核心问题已逐项修复并回归。第三轮的通知 query token 和普通 route 贯穿缺口已关闭；2026-09-29 又清理 browser、terminal、ADB 与 trajectory 当前客户端 URL token。三项小型 Work 错误映射缺口在现有交付文件中没有具体明细，仍列为 BLOCKED，不猜测修复。独立审阅不替代双容器或出网验收。
- 修改后完整 Work WebSocket 测试文件：27 passed。独立分发测试 3 passed。旧 Work clean-install 报告：Node 22.13.0、pnpm 10.4.1，904 passed/11 skipped，类型/构建通过；单独归档。
- 旧 Work 本地 MariaDB 11.4 合成验证：先应用现有 Drizzle 迁移，14 项集成用例及 SEC-02 0036 一项共 15 项通过；容器绑定回环端口且数据使用 tmpfs，随后停止并移除。第一次未应用迁移的空库尝试失败，修正初始化顺序后在新临时库复验通过。浏览器插件 Node 测试 42/42、语法、manifest、settings-dom 检查通过。

## 未完成和发布阻断

- Colima 0.10.3 已按原 profile 启动且未重置；锁定 PostgreSQL 镜像已拉取，专用容器 `work2-pg-accept-20260929` 与独立卷 `work2_pg_accept_20260929` 保留。当前 PostgreSQL 文件 8/8 通过；不再把数据库不可用列为阻断。
- entry/A/B Octop runtime 镜像仍未构建成功，因此数据库角色权限、A/B 卷、secret 实际消费、目标身份负向验证和受控 egress 仍未运行。P2 物理双机构隔离仍为发布阻断。
- 早先 Chrome 尝试的 `ERR_FILE_NOT_FOUND` 已由后续 1.1.0 独立试验纠正：Chrome 显示 1.1.0 弹窗，合成 `chrome.storage.local` 值经 `chrome://restart` 后读回一致并清除。只验收弹窗与本地存储，不含真实业务页面、Feishu 停用候选或外部请求观测；临时 profile 与源码副本已移入可恢复废纸篓，未操作用户常用 Chrome。
- 生产只读盘点、commit/push、仓库规则、迁移、配置清理、凭据撤销和 Work2 切换均未执行；这些动作继续按单独授权处理。回滚不得重新开放飞书或 PixelRAG.
