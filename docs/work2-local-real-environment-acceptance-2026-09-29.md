# Work2 本地真实环境续验记录（2026-09-29）

> 2026-09-30：本地entry/A/B、真实PG故障恢复、TLS负向、长连接、四进程额度、挂载/出网已补实跑；权限权威写隔离及产品验收仍阻断。当前最终候选及状态以 [固定范围验收](work2-fixed-scope-acceptance-2026-09-30.md) 为准，本文件下文为历史记录。

## 结论

本轮达到“本地候选阶段部分真实环境收口”，但**仍不能替换生产 Work**。真实 PostgreSQL、备份恢复、持久化防重放、撤权和额度竞争已经实跑；entry + A/B Octop 双容器、角色/卷/secret/受控出网、旧 Work 业务数据迁移、跨版本升级与恢复、真实业务闭环仍未通过。

候选分支为 `work2/p0-p2-20260928`，基础 HEAD 为 `9630df997c4d74dc49effae6102f96423b0059ff`，工作区包含未提交修改，`deploy/work/build-manifest.json` 的 `work_sha` 保持 `null`。未提交、推送、部署、迁移生产、导入真实机构数据、删除现有卷或发起付费外呼。

当前完整源/配置清单为 3,698 个常规文件，正文 SHA-256 为 `05234fd9449fc190c1ba0a90424a4069e5339a8ace497df1db7930806f82f168`，文件位于本地证据目录 `work2-source-manifest-local-real-env-20260929.sha256`。清单排除 symlink、ignored 证据/依赖目录和三份会继续更新的状态文档。

## 环境与证据

- 执行时间：2026-09-29 约 12:34–12:58（Asia/Shanghai）。
- Colima 0.10.3 使用现有 profile 启动，未重置；Docker 命令显式使用 `DOCKER_HOST=unix:///Users/happy/.colima/default/docker.sock`。
- PostgreSQL 镜像：`pgvector/pgvector:pg16@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b`。
- 测试容器：`work2-pg-accept-20260929`；独立卷：`work2_pg_accept_20260929`；仅绑定 `127.0.0.1:55432`。容器和卷保留，未删除。
- 只使用合成数据库凭据、测试数据和本地测试资源；证据中不记录密码、token、证书私钥或真实机构资料。

## 验收台账

| 验收项 | 命令/方法（敏感值脱敏） | 预期 | 实际 | 状态 |
| --- | --- | --- | --- | --- |
| PostgreSQL 服务就绪 | `docker exec work2-pg-accept-20260929 pg_isready -U <test-user> -d <test-db>` | 容器内数据库接受连接 | `accepting connections`，退出码 0 | PASS |
| PostgreSQL 初始化、CRUD、probe、真实 backup/restore、setup bind、knowledge schema、v3→v5 重复迁移 | 设置由容器合成环境组装的 `OCTOP_TEST_DATABASE_URL`，并运行 `.venv/bin/python -m pytest -q tests/integration/test_postgresql_control_plane.py`；`pg_dump/pg_restore` 由容器内 PostgreSQL 16 工具执行 | 当前文件全部收集项通过，无 skip | 当前实际收集 8 项，`8 passed in 6.21s`，退出码 0 | PASS |
| 防重放、重启、撤权 | 同一真实 PostgreSQL 测试中的 `test_work_control_plane_revocation_and_restart_block_pending_execution` | 同一 handoff 至多一次消费；重启后拒绝；撤权后上下文失效 | 两路并发仅一次成功；重启后消费返回拒绝；撤权后 grant/context 均失效 | PASS |
| 额度并发 | 同一测试中 40 路并发争用；此前已有 1 次 reservation | 仅剩 19 次成功，task/user/organization 均不超过 20 | 19 次成功；三层计数均为 20 | PASS |
| Dashboard/WebSocket URL token | browser、terminal、ADB 使用共享 `octop.auth.<JWT>` subprotocol helper；服务端复用 `extract_websocket_auth`；query 仅保留兼容 fallback | 当前 Dashboard URL 不含登录 token；服务端选择固定 `octop.chat` | 后端路由/trajectory 受影响集合 `54 passed in 31.30s`；前端完整测试 `207 files / 1,089 passed` | PASS |
| trajectory SSE URL token | 原生 authenticated `fetch` + 现有 `requestStream`，不新增依赖；分块 SSE 解析回归覆盖跨 chunk frame | `Authorization` header 鉴权，URL 只有 `after_seq`，断线按最后 seq 重连 | 新增模块与 hook 回归通过；Dashboard 完整测试通过 | PASS |
| Dashboard 类型与测试构建 | `npm run build:test` | tsc 与 Vite test build 成功 | 退出码 0；保留既有 dynamic-import 和大 chunk warnings | PASS |
| Python 格式/静态检查（受影响文件） | `ruff check`、`ruff format --check` | 无 lint/format 失败 | 均退出码 0 | PASS |
| entry + A/B Octop 双容器 | 完整 Dockerfile 构建和候选 wheel 最小镜像尝试 | 生成可运行 runtime 镜像并启动 entry/A/B | 完整构建停在 Dashboard `npm ci` 长时间下载；无锁 pip 路线进入 resolver backtracking，均主动终止，未生成镜像 | BLOCKED |
| A/B 角色、卷、secret、受控出网负向验收 | 依赖可运行的 entry/A/B runtime 容器 | 实际检查容器权限/挂载/凭据和批准/未批准目的地 | 未运行，不以 Compose 静态声明代替 | BLOCKED |
| 三项 Work 错误映射缺口 | 从当前进度、readiness、build manifest 和代码中回查 | 找到每项入口、触发条件、当前/预期行为后 TDD 修复 | 现有交付文件只写“三项”，没有具体三项内容；未猜测修改 | BLOCKED |
| 旧 Work 业务数据迁移与对账 | 真实旧库备份、迁移、权限/关联对账 | 空库/已有库/中断/恢复和数据对账均通过 | 未使用真实旧 Work 数据 | NOT_RUN |
| PixelRAG/飞书永久停用运行验收 | 新容器、历史任务和升级后验证入口仍关闭 | 无重新启用 | 本轮未获得可运行 Work2 runtime 镜像，未做容器运行验收 | NOT_RUN |
| 资料→任务→可编辑成果→人工复核→导出 | 登录态端到端业务验收 | 完整业务闭环通过 | 未运行 | NOT_RUN |
| Octop 跨版本升级及两类恢复 | 旧版本→候选升级；无新增写入/有新增成果两种恢复 | 不丢新增成果，可核对恢复 | 未运行 | NOT_RUN |

## 诊断性失败（不计为候选失败结论）

- 第一次前端组合命令从仓库根目录执行，因根目录无 `package.json` 退出 254；随后在 `dashboard/` 重跑通过。
- 第一次 PostgreSQL 复跑误把测试容器用户/数据库写成 `postgres`，连接池超时后手动中止，退出 2；容器并无该角色。随后从容器合成环境读取 user/db/password（不输出值）重跑，8/8 通过。
- 最终复核第一次未把现有容器版 `pg_dump/pg_restore` wrapper 加入 `PATH`，因此结果为 `7 passed / 1 skipped`；补齐同一 wrapper 后重跑为 `8 passed in 6.05s`，退出码 0。
- 当前测试文件实际收集 8 项，不是早先摘要中的 9 项；本记录以可复现的 `--collect-only` 与本轮运行结果为准。

## 计数与 warnings 边界

- 历史计数说明订正：`make check-all` 执行静态门禁和 Python suite，不运行 Vitest；`3,903 passed / 20 skipped / 21 pytest warnings` 与 Dashboard `1,087 passed` 不重叠。不要直接相加作为业务验收进展。2026-09-29当时未重跑完整门禁，2026-09-30最终完整门禁另列于最新报告。
- 本轮 Dashboard 增至 `207 files / 1,089 passed`。完整运行仍打印既有 jsdom `getComputedStyle` 测试噪声，但退出码为 0；Vite 仍有 dynamic import 与大 chunk 提示。
- 旧 20 skipped 的分类仍为：9 项 Linux root/bwrap、9 项 PostgreSQL、1 项未传 wheel 路径的分发合同、1 项 AgentManager monkeypatch。此次直接运行真实 PostgreSQL 文件关闭了其中 8 项 control-plane 场景；checkpoint-history 和其他 skip 是否关闭必须在下一次完整门禁中重新计数，不能从局部运行推断。

## 准入结论

- 已关闭：锁定 PostgreSQL 镜像/Colima 前置、当前 PostgreSQL 文件的 8 项真实场景、真实备份恢复、持久化 handoff 防重放、重启拒绝、撤权、任务/用户/机构额度竞争、当前 Dashboard 实时 URL token（chat、notification、browser、terminal、ADB、trajectory）。
- 仍阻断：真实 entry/A/B runtime 容器、角色/卷/secret/egress、三项错误映射明细、旧 Work 数据迁移、PixelRAG/飞书容器运行停用、跨版本升级/恢复、登录态业务闭环。
- 下一阶段仍不具备受控预发准入条件，更不具备替换生产 Work 的条件。
