# Work2 固定范围验收收口（2026-09-30）

## 结论与边界

当前本地候选已封版：代码、依赖、构建产物和最终完整门禁对应同一文件摘要。Python 门禁 3,930 passed / 21 skipped / 13 warnings；Dashboard 完整复跑 1,089 passed；真实 PG/分发 13 passed。固定范围验收仍未全部通过。
申请受控预发：BLOCKED。申请生产替换：BLOCKED，且 NOT_AUTHORIZED。
旧 Work 迁移、机构业务闭环、Octop 跨版本升级和两类业务恢复均 BLOCKED；下表列出具体原因，不以测试数量抵消。

只操作独立本地实验环境、合成数据和测试证书。未提交、推送、合并、预发/生产部署、修改生产数据库/配置/DNS、导入生产数据或付费外呼。现有卷、备份、dirty/untracked 改动及失败日志保留。长连接用 observer 临时流式 fixture 已恢复为原文件，逐字节比对通过。

## 候选身份

- 工作区：/Users/happy/Documents/Codex/2026-09-28/work2-octop/candidate/happykkAi-work-232030f。
- 分支：work2/p0-p2-20260928；基础 HEAD：9630df997c4d74dc49effae6102f96423b0059ff。
- work_sha=null；dirty=true。不是正式提交身份，也未发布到 registry。
- 常规源文件清单摘要：48d2e47478b902fdfdf7af93f3815b93c94f38f48787b6e8fba763d6b9f63522；3,699 个常规文件。含 tracked/untracked 与符号链接元数据的保全 archive SHA-256：512a96badfd8ae8ce99d810fcf3fbea53076923b982dd9db436a50e23bc0507b。
- 清单算法：非 ignored 的 tracked/untracked 常规文件，按相对路径排序，将 SHA-256、双空格、路径和换行组成正文后再取 SHA-256。明确排除 docs/work2-*、deploy/work/build-manifest.json 以及 ignored 的证据/依赖目录。唯一 tracked 目录符号链接不纳入常规文件清单，单独记录：src/octop/infra/agents/experts/library/cvm-cluster-doctor/skills/cvm-ai-doctor → ../../cvm-ai-doctor/skills/cvm-ai-doctor，Git mode=120000；archive 保全它的链接元数据。清单不是被排除文档或 secret 的摘要；实验配置另列。
- 本地镜像：work2-local:final-fixed-20260930；Image ID：sha256:e9b6136e055958f16214ea28e005608eb0a96c3be4a3efb8606f578bfaf4c8cb。
- Docker 本地元数据返回同值的 work2-local@sha256 引用，但没有推送到 registry，不能称为可供正式部署拉取的 registry RepoDigest。manifest 的 registry_repo_digest 保持 null。
- 仅验证 linux/arm64，目标服务器架构 UNKNOWN。
- Python 3.12.13、uv 0.12.19、Node 24.21.0、npm 11.19.0；uv lock --check --offline 退出 0。镜像沿用此前 hash-locked source-build 依赖层，此次离线 --no-deps 重装两个候选 wheel 并 pip check；没有重新解析无锁依赖或改动锁文件。

| 产物 | SHA-256 |
| --- | --- |
| Octop wheel | 37fb77afd5a365b86ddea7dadb5bbd9c08e87b397216e39741cbd4b0bc973352 |
| Octop sdist | 5aa33021e78fca2344d0232ede6b7e651341402063fc1bab53359b36661ab407 |
| work_platform wheel | 28fa94e99daa088b0c177058dd3ad4d8e5ee2fe4a6190ed7b6b995ba4fcc0bac |
| work_platform sdist | 671122b3552bdde84235b73ac4e3591e6541e6d19497f07c056410fb0052db15 |
| Octop uv.lock | 3ecad1ef86f5e9b588f100df7b7af73859f234be9dbe631da90ed2fa9db7611c |
| Dashboard package-lock.json | f624f684fc3c0f2b9f84be656428a5345077959d3f806cb05be5b489b8b892f9 |
| work_platform uv.lock | 873679d6c05d09d1357e5f81a8a1e4155cc574fc8f2a2fa4cb9a7a359cac44d4 |
| 实验 compose.json | b5d6bf00fc5db6dbe7838484c4f6a312071e235dc4d65c916d368a205bfe7a5d |
| compose.final-fixed.json | e24533779a4e40d39b05f6d9ae5415ac7c31c2cbcabe5d8a7b553d7cb11ac02f |
| 恢复后的 observer.py | 76adabb9beb8ec747d97d5dffcf0bde57043b1b390b2de51135ffb0ee6faff0a |
| entry/A/B 的 /data/.octop/config.json（仅摘要） | 085c3a28394f7674993637f9f28a292436360db63bda221a70cf513b00f6576a |
| tracked patch | f3294b37ab42cb2ac844f5fb07fa1b45587317a11de5244e57d68b5e8a883dd3 |

Octop wheel 内 Python/生成 Dashboard 和当前源码逐文件比对无差异；work_platform wheel 另作逐文件比对。此前 Node24 Dashboard 构建日志保留，不因仅后端修复重建未变化的前端。

## 环境、命令与证据索引

下文 E = 候选下 .superpowers/sdd/Work2_Octop_完整替换与持续升级计划_20260927/real-env-20260930。
S = /Users/happy/.codex/state/plugins/codex-security/scans/happykkAi-work-232030f/artifacts-6e0053d7477fd571829d6132eb3483bcb74d1cc03abe7868fb2095e6879de966。
T 是安全插件返回的 temporary 目录，仅作执行暂存；最终验收日志以 S 下持久文件为准。
所有实际命令在候选目录执行，Dashboard 命令在 dashboard/ 执行。PATH 显式加入上述 uv/Node24；UV_NO_SYNC=1；Docker 使用 unix:///Users/happy/.colima/default/docker.sock。
每项候选均为上述完整摘要，除明确标注“历史/组件证据复用”的记录。日期时间为 UTC，日志正文优先于文件时间。

| 验收项 | 环境、实际命令与时间 | 预期与实际 | 退出码 / 状态 / 证据 |
| --- | --- | --- | --- |
| 冻结构建 | 06:41:53–06:42:12；uv build --offline --out-dir E/final-fixed-build .；同命令构建 packages/work_platform | 两个 wheel/sdist 成功；首次 --no-build-isolation 因当前 venv 无 hatchling 退出 2，未改依赖，改用项目声明的隔离构建离线完成 | 0 / PASS / E/final-fixed-isolated-build.log；失败保留 E/final-fixed-build.log |
| 本地镜像 | docker build -f E/Dockerfile.final-fixed -t work2-local:final-fixed-20260930 E；随后 Compose up -d --no-deps entry a b | 离线安装成功、pip check 无冲突，entry/A/B 使用相同 Image ID；首次探针先于实际业务就绪而断连，不算通过 | 0 / PASS / E/image-final-fixed-build.log、E/start-final-fixed.log |
| 共用 HTTP 数据库错误映射 | 06:52:46–06:53:27（文件时间）；uv run pytest tests/unit/work/test_realtime_boundary.py tests/unit/work/test_error_mapping.py tests/unit/work/test_work_entry_websocket.py -q | 根因：setup lockdown 在 router 之前访问旧 PG 连接抛 AdminShutdown；原局部 handler catch 无效。WorkBoundary 对尚未开始的 HTTP 响应返回 503，已开始的响应不发送第二个响应；无自动业务重试或放行 | 0 / PASS，33 passed / E/focused-final-fixed.log；红测 S/artifacts/20260930/failures/pre-router-db-red.log |
| 全量后端/前后端静态门禁 | 06:41:17 起；make check-all PYTEST_JOBS=4 | Python 3930 passed / 21 skipped / 13 warnings，922.22s；Ruff、前后端类型/格式与 ESLint 门禁完成，保留 warnings。完成后清单 cmp 一致，无源码漂移 | 0 / PASS（实际执行门禁，跳过不计通过） / E/check-all-final-fixed.log |
| Dashboard 完整测试 | 06:45:59 起 npm test；06:51:32 起 npm test -- --maxWorkers=2 | 第一次 24 failed / 1065 passed，311.93s；22 个超时及 2 个断言失败。主机 load average 曾达 21.62。仅降低并发、不改代码/断言/超时，重跑完整 207 文件后 1089 passed，286.57s | 第一次 1 / FAIL；完整复跑 0 / PASS / E/dashboard-final-fixed.log、E/dashboard-final-fixed-bounded.log |
| 真实 PostgreSQL 与分发 | 06:43:57–06:44:19；uv run python E/verify_pg.py final-fixed-build/work_platform-0.1.0-py3-none-any.whl | 专用 work2-pg-accept-20260929，合成库；真实初始化、升级、重复迁移、备份恢复、撤权/重放、额度跨 UTC 日、checkpoint 及分发合同，13 passed | 0 / PASS / E/postgresql-final-fixed.log。只允许测试文件 reset 这个专用可丢弃库，不触碰三个 lab 应用库 |
| TLS / 错目标拒绝 | 06:44:26–06:44:35；uv run python T/artifacts/verify_failure_recovery.py | 错目标 403；无客户端证书、错误 CA、hostname 不匹配均 transport 拒绝；未静默改投 A | 0 / PASS / S/artifacts/20260930/failure-recovery-final-fixed-health.log |
| PG 停机/重启与持久重放 | 同一 helper，停止精确 pg-b 容器并 finally 启动，不删卷 | 停机不能取得执行连接，A/B model calls delta=0；恢复前三次 503、随后 403；验证票据仍未过期，证明不是 TTL 假拒绝；新连接 ping/pong 恢复。原 500 未再复现 | 0 / PASS / 同上。仅票据消费证明，不是任务/外部副作用完整幂等证明 |
| 长连接与失效会话 | 06:44:55–06:46:39；uv run python T/artifacts/verify_long_final.py | 持续输出 89.54s；空闲传输心跳 79.39s；chat/notifications 空闲过期关闭，退出关闭，撤权关闭，断开重连均符合断言。Uvicorn ping interval/timeout=20s，relay close_timeout=5s，handoff 建连 TTL=60s，边界闲置复核=5s | 0 / PASS / S/artifacts/20260930/long-final-fixed.log。lab 无生产前置代理；不承诺任务准备/同步阻塞期间也在 5s 内关闭 |
| 跨进程额度竞争 | 06:44:56–06:44:57（文件时间）；uv run python T/artifacts/verify_quota.py；PYTHONPATH=packages/work_platform/src；专用共享 PG | 四个进程争用 task20/user UTC100/org UTC500 最后一格，各一次成功；任务前一天已20次时新一天仍拒绝。历史计数保留 | 0 / PASS（额度子项） / S/artifacts/20260930/quota-final-fixed.log |
| 同 runtime 第二工作进程 | 同一额度 helper，创建第二个 WorkControlPlane | 实际 context_is_current=false，构造时 _block_incomplete_runs 误阻断仍活跃第一进程任务 | helper 0 但子项 FAIL / 同上。诊断脚本退出 0 不代表所有子项 PASS；不支持据此放行多 runtime worker |
| A/B 卷、secret、网络与 DDL | 06:47:02–06:47:13；uv run python T/artifacts/verify_isolation_corrected.py | 实际 mount 无对方 private volume/secret、无 Docker socket、每 runtime 一张网络；本机构 observer 可达，对方 observer/PG 及 1.1.1.1:443 不可达；真实角色 database/schema CREATE=false | 0 / PASS（有限隔离子项） / S/artifacts/20260930/isolation-corrected-final-fixed.log。首次 helper 错用不存在的 fetch_one 退出 1，修正 helper 后重跑，未改候选 |
| 平台策略/额度写权限 | 同一 helper 只读 has_table_privilege 检查 | A/B role 对 work_organization_policies 和 work_budget_counters UPDATE=true；DML-only 不等于不拥有平台级权威写能力 | FAIL / 同上。需确定权威控制库和 runtime 最小表级写权限；未通过放宽/重做权限掩盖问题 |
| 普通业务路由与实时拒绝 | 06:56:44–06:56:47；uv run python T/artifacts/verify_live.py | 先前两次并行运行因登录 ReadTimeout / opening handshake timeout 退出1。高负载测试结束后同镜像、同 helper、同超时完整通过：合成模型回复正确、A0/B1、query/Origin/越机构/远控拒绝且 attempts delta0、退出及成员撤权后连接和重连拒绝、退役 HTTP 拒绝 | 0 / PASS / S/artifacts/20260930/live-final-fixed-bounded-load.log；此前失败保留。不是机构成果复核业务闭环 |
| 日志脱敏 | 最终 live 完成后 docker logs entry/a/b，逐个只搜索 canary 是否存在，不输出日志原文 | 已实际发出的 query canary 不在三个 runtime 日志中 | 0 / PASS / 最终一致性复核记录；lab 无生产代理，其日志仍 NOT_RUN |
| 三项错误映射 | entry InvalidHandshake、runtime 配置503/权限403、enqueue+block_run 双失败仍 error+done | unit/integration 已有对应断言，最终全量门禁验证；真实 PG 故障只覆盖数据库映射。不伪称三项已全部完成容器入口故障注入 | 局部 PASS / 其余实际故障注入 NOT_RUN |

## 产品级固定验收及明确阻断条件

| 项目 | 当前证据与实际状态 | 完成所缺条件 |
| --- | --- | --- |
| 旧 Work → Work2 合成迁移与权限/附件对账 | BLOCKED。仅有 authorization/capability/runtime/handoff 包；缺业务导出/转换/import_batch、旧新 ID 映射、附件 ACL/历史引用/审核与额度对账工具。PG native backup/restore 不等于旧 Work 迁移 | 实现已约定转换与对账，再提供旧结构合成 fixture、可读附件、成员权限、故障中断/恢复的逐对象结果 |
| 资料→任务→可编辑成果→人工复核→导出 | BLOCKED。Work 的 project_id=None、allowed_asset_versions=frozenset()；Project 仍 Planned；前轮登录 API 的 projects、legacy、成果 versions 和 runs 为404。不能用管理员页面或模型一句回复替代 | 普通成员、不同机构、复核角色的已约定业务实现与可运行全链 fixture |
| 带 Work 定制 Octop 跨版本升级 | BLOCKED。没有实际两个软件版本配对、业务升级 fixture、升级转换与定制/停用保护的完整实跑工具。机构 runtime A/B 不是软件版本 A→B | 明确旧版本/目标版本及摘要，运行升级并对账定制、业务、权限、退役能力 |
| 无新增写入业务恢复 | BLOCKED。仅 native PG 备份恢复，不是完整 Work 业务切换恢复 | 切换前业务快照、冻结写入/恢复步骤、权限与附件可访问对账 |
| 已产生新成果后的业务恢复 | BLOCKED。没有新增成果/额度保全和兼容反向转换证明 | 冻结写入、保全新增成果与额度、验证兼容回退或前进修复；不得直接旧快照覆盖，不得无证明恢复旧库可写 |
| PixelRAG / 飞书永久停用 | 局部源码/unit 与真实 HTTP 拒绝已有；旧配置、历史任务重试、回调、完整升级后的停用及历史保留 NOT_RUN | 在最终业务 fixture 与跨版本升级里验证不会复活；保留历史资料/审计，不只是隐藏菜单 |
| 跨机构同用户日100与统一撤权 | NOT_RUN / BLOCKED。lab work_entry/work_a/work_b 是分离库；四进程额度证明仅在同一共享库。不是跨三库集中账本/统一撤权证明 | 明确权威身份/撤销/全用户额度库及跨机构执行同步契约，然后实跑 |
| 完整任务及外部副作用幂等 | NOT_RUN。nonce 原子消费与 attempt 原子预留已证实，但不能推出任务和外部副作用只发生一次 | 本地非付费外呼 sink、任务恢复与副作用幂等键实际对账 |
| 生产架构、代理、浏览器业务、SBOM/完整许可证 | NOT_RUN；SBOM=null，licenses=[] | 获取明确目标与授权后完成相应验证，不把本地 ARM64/健康检查代替生产业务验收 |

产品缺口依据：E/business-implementation-inventory.txt、E/business-implementation-gaps.txt、E/business-route-inventory.json，以及 packages/work_platform/src/work_platform/authorization.py。这些盘点是前轮组件证据，当前没有改动业务包/路由注册来补齐缺失功能。

## 跳过、警告和计数边界

最终完整门禁确认 21 skipped。逐项原因复用此前 accepted 门禁的 -ra 清单，相关8个测试文件 SHA-256 与最终候选逐项一致，运行平台和缺失全量 PG/wheel 参数未改变；未删除用例或新增 skip。完整门禁与独立真实 PG/分发结果分别报告，不直接相减拼出一次无 skip 的门禁。

| 跳过项（位置） | 原因 / 发布影响 |
| --- | --- |
| unit/browser/test_browser_setup.py:383 | macOS 没有 /root；目标平台语义仍待验证 |
| unit/infra/utils/test_bwrap.py:133 | Linux+bwrap 不可用；不能宣称 Linux sandbox 验收 |
| unit/infra/utils/test_host_dirs.py:93 | /root 不可用；目标平台验证未做 |
| unit/infra/utils/test_host_dirs.py:108 | /root 不可读；目标平台验证未做 |
| integration/test_bwrap_jail.py:181 | Linux+bwrap；NOT_RUN |
| integration/test_bwrap_jail.py:190 | Linux+bwrap；NOT_RUN |
| integration/test_bwrap_jail.py:205 | Linux+bwrap；NOT_RUN |
| integration/test_bwrap_jail.py:220 | Linux+bwrap；NOT_RUN |
| integration/test_bwrap_jail.py:242 | Linux+bwrap；NOT_RUN |
| integration/test_postgresql_checkpoint_history.py:15 | 全量未设合成 PG URL；最终专用 PG 单独实跑 PASS |
| integration/test_postgresql_control_plane.py:63 | 同上，独立真实 PG PASS |
| integration/test_postgresql_control_plane.py:124 | 同上，独立真实 PG PASS |
| integration/test_postgresql_control_plane.py:145 | 同上，独立真实 PG PASS |
| integration/test_postgresql_control_plane.py:225 | 同上，独立真实 PG PASS |
| integration/test_postgresql_control_plane.py:245 | 同上，独立真实 PG PASS |
| integration/test_postgresql_control_plane.py:310 | 同上，独立真实 PG PASS |
| integration/test_postgresql_control_plane.py:360 | 同上，独立真实 PG PASS |
| integration/test_postgresql_control_plane.py:419 | 同上，独立真实 PG PASS |
| integration/test_postgresql_control_plane.py:609 | 同上，独立真实 PG PASS |
| work_contracts/test_distribution.py:20 | 全量未设 wheel 路径；最终构建 wheel 的独立分发3项 PASS |
| unit/agents/test_agent_manager.py:1302 | test_build_harness_config_passes_default_model_without_embedded_providers；既有 monkeypatch 与 SecurityPolicy.apply_to_config 不兼容，default_model 转发及不嵌入 provider 的该测试缺证据；未关闭，不属于通过证据 |

最终 pytest 的13 warnings：Lark SDK datetime/事件循环弃用8次（4 worker重复），websockets/uvicorn 弃用4次，Discord audioop 弃用1次。依赖升级兼容风险仍在；不是“全部无影响”，也不代表停用飞书失效。旧报告的21条是另一轮 worker 计数，不是本轮数值。
ESLint 67 warnings（0 errors）、Vite chunk 提示、Dashboard jsdom getComputedStyle 噪声分别保留，不合并到 pytest warnings。
Makefile 的 check-all 执行前后端静态检查和 Python 测试，不运行 Vitest；Dashboard 1,089 与 Python 计数不重叠。历史报告“Dashboard 已包含在3,903中”的说法更正为不包含；不把两套数量相加当业务验收进展。

## 中断、失败与版本关系

- 原 check-all-verified.log 停在 mypy：用户 turn interruption，OS 退出码 UNKNOWN，INTERRUPTED；原 long-connection.log 只有 connected：INTERRUPTED。不是 PASS，也没有证据认定 OOM 或产品卡死。
- source f0dd4905…、sealed b010677d…、accepted ee6805b… 均为中间候选，后续源码变更使其 SUPERSEDED。不得将它们的3925/3928/3929结果拼成本候选全量通过。
- 空闲失效连接：先真实复现 idle 授权仍开放，再修复共用 receive 周期复核/close 串行化；原红/绿日志保留。
- 任务额度跨 UTC 日：四进程真实 PG 红测允许第21次；修复同 task advisory transaction lock 与跨日 SUM，最终真实 PG/helper 拒绝。仍保留20/task、UTC100/user、UTC500/org。
- PG恢复500：局部 handler 加 OperationalError 没覆盖 setup lockdown。撤回这个局部 catch，改 shared Work HTTP boundary；根因红测和最终503→403→业务恢复链路已对应最终 wheel。
- 数据库故障 helper 的 invalid connection ID、隔离 helper 的 fetch_one 和非隔离构建缺 hatchling 均属 fixture/toolchain 失败；失败日志不覆盖，修正后仅复跑受影响步骤。
- 独立只读审阅覆盖空闲鉴权补丁和当时相关代码；后续 task 跨日锁与 shared PG HTTP 映射没有新的独立全量安全审阅。不能沿用“无新增高等级问题”声称最终全差异获独立验证。

## 最终交付定位

持久证据索引（S/artifacts/20260930/）：

| 文件 | SHA-256 |
| --- | --- |
| failure-recovery-final-fixed-health.log | 099ff0fa96d11c958f8e9be9981c3e57ae75a36597f3ecd2e5536bbd87eed6bf |
| long-final-fixed.log | 135aa7722d6d2feba048e04891ba852cad6b242266dd4c4e5b77dd825a53c268 |
| quota-final-fixed.log | cda661ab62a90bffc974a4cc3e0283fc8e2a70a9eabb33bac75089eca5222d02 |
| isolation-corrected-final-fixed.log | 2cc652d63e83447e5c23b1da6d30f4fa484e4f43e708669528ad797c18005b6c |
| live-final-fixed-bounded-load.log | 52a100760658383404e5027f345a24a9bc1f2f6e4e624850aa20c691a081ecd4 |

同目录 helpers/ 保留此次实际执行的5个 helper 及 long-observer-fixture.patch；原 observer 已恢复，此 patch 仅供合成 lab 复验持续流，不用于生产。failures/ 保留根因红测、原500、启动断连、并行负载超时及隔离 helper 失败的脱敏文本（已移除合成密码/JWT值）。Dashboard 初次24失败的完整原日志保留在 E。不覆写旧失败或用后来通过抹掉失败。

源清单 E/candidate-final-fixed.json、完成后复核 E/candidate-final-fixed-recheck.json（cmp 退出0）、源码保全 E/source-final-fixed-20260930.tar.gz、tracked patch E/final-fixed-changes.patch（untracked 由 tar 保全）、构建 E/final-fixed-build、manifest deploy/work/build-manifest.json。历史保全文件未覆盖。源码、wheel/镜像、实际运行的 entry/A/B 与本次验收匹配；更新状态文档不会改变明确排除它们的源清单。
当前准入依据是“每一道门槛的证据与具体缺口”，不是测试总数。缺产品实现的项目保持 BLOCKED；本轮不新建这些功能来冒充验收，下一轮需先取得对应实施范围/权威控制面决策，再推进。
