# Work2 当前成果交接 — 2026-09-30

## 1. 交付范围与结论

本次按用户最新指令：把已有 Work2 代码、剩余修复和交接文档推送至
GitHub；不处理飞牛，不继续服务器部署，不替换现有 Work。
当前成果是可继续开发和验收的候选，不是已获放行的正式版本。

- 仓库：<https://github.com/happykkAi/work>
- 交付分支：`release/work2-20260930`
- Draft PR：<https://github.com/happykkAi/work/pull/1>
- 基础 main：`232030f46c5450801ca87809f8a4da57aefc5a05`
- 本轮代码修复基点：`5d37e33e8b87bab42a522e66b6d7e279f29aa03d`；
  文案重复项修复：`ca975ff528b8a12dcc05b0fe0c9e7b94b22d47e3`。
  本文档随后独立提交。实际最新提交以远端分支/PR HEAD 为准。
- 未合并；不存在本轮合并 SHA、生产发行标签、预发或生产部署版本。
- 当前没有新的可访问 Work2 测试入口；现有 `work.shegongai.com` 未切换。

正式工作目录：
`/Users/happy/Documents/Codex/2026-09-28/work2-octop/delivery-20260930`

原候选完整保留：
`/Users/happy/Documents/Codex/2026-09-28/work2-octop/candidate/happykkAi-work-232030f`

不要覆盖原候选的未提交文件、私有测试数据库、测试卷、日志和恢复材料。

## 2. 已修复内容与版本

| 项目 | 根因/处理 | 修复提交与验证边界 |
| --- | --- | --- |
| 多进程启动误阻断任务 | 启动清理原来无条件修改同 runtime 的所有任务。引入执行者身份、独立 PG session 所有权锁与 fencing，只清理失去所有者的任务，不自动重试外部副作用 | `acb12fd57a43c6a3133a532500c23d57948c13eb`；真实 PG、多进程和接管边界测试通过；最后候选仍需全量复验 |
| runtime 策略写权限 | runtime 原可直接改策略与额度表。共享 authority DB 使用机构绑定、RLS、限定数据库函数；合法 manager 与离线迁移 owner 分离 | 同上；真实受限角色的合法操作及直接 SQL 越权拒绝通过，未授 superuser/全表写权限 |
| 检查流程 `eslint: not found` | 锁定 Dashboard 依赖在全栈检查之后才安装，已调到检查前 | 同上；后续 Work CI 成功执行全栈门禁 |
| Portable Python 404 | 发布目录和资源标签不同，统一真实 `20260807` / Python `3.12.13` | 同上；历史 Desktop CI 四架构打包成功；新增启动检查仍需新 CI 结果 |
| 独立 Work 环境缺 YAML parser | 开发依赖补已有版本 `pyyaml==6.0.3` 并锁定 | `8c31b7b344eef7cd2d2d436cda61fac5f7f42278`；独立合同通过 |
| 被跳过的模型转发用例 | 修复 dataclass 配置和 provider 注册测试 fixture，恢复原断言与用例 | `4f57db58a5b29e051ab56909d6b5ac531bd0ffb4`；95 passed，无模型外呼 |
| 历史数据保全 | 严格 catalog、关系/状态/文件 hash 校验，checkpoint 断点续导和冲突拒绝；新增历史表不默认授 runtime 读取 | `b3821d5c2932b771eb0bf4a9e4e2b3297164b2f7`；合成 PG 演练通过，但只到 `IMPORTED_NOT_ACTIVATED` |
| 计量外模型旁路（Important） | 普通知识库 embedding/OCR 与 voice 未经过 Work 额度/策略。共享领域入口在 Work 模式拒绝未计量远程模型，本地文本处理和 standalone 行为保留 | `4a824eadeab9f91c006b57786bd63bef9f8eeb24`；179 定向用例通过，真实 JWT/HTTP + transport stub 拒绝与零外呼，不是真实供应商验收 |
| wheel/desktop 缺 Work 包（Important） | 源码测试路径和 Docker 单独安装掩盖普通发行包缺 `work_platform`。根 wheel/sdist 包含现有 Work 模块，smoke 真实 import server/launch | `5d37e33e8b87bab42a522e66b6d7e279f29aa03d`；真实构建、隔离提取及启动 import 通过 |
| Windows 两个测试失败 | ADB 鉴权测试局部模拟 POSIX 条件，不跑 PTY；workflow 文件显式 UTF-8，保留原断言 | 同上；本地定向通过，真实 Windows 新 CI 尚待确认 |
| 重复 locale key（Minor） | en/zh 各删去一份相同 `retiredFeatures`，保留原文案及停用语义 | `ca975ff528b8a12dcc05b0fe0c9e7b94b22d47e3`；72 个 i18n 用例通过，提交 hook 静态检查和 Dashboard 构建通过（testmon 没有选中用例，不算完整回归） |

额度口径仍为每任务 20、每用户 UTC 日 100、每机构 UTC 日 500。
PixelRAG 永久停用，飞书整体关闭；没有备用、静默回退或重新接入。

## 3. 已有验证与不可继承的边界

已完整验证的历史源码是 `0eedc803b24c6b09d0432bf882e540bd91eccb72`，
不是上述新增修复后的最终候选：

| 验证 | 实际结果 | 证据 |
| --- | --- | --- |
| 本地 `make check-all PYTEST_JOBS=4` | exit 0；3944 passed / 25 skipped / 13 warnings | `.superpowers/delivery/check-all-0eedc80.log` |
| Dashboard 完整测试 | exit 0；1089 passed / 207 files，与后端分开，不能相加 | `.superpowers/delivery/dashboard-0eedc80.log` |
| 真 PG、多进程、native backup/restore、Work 与分发合同 | exit 0；94 passed / 46 subtests / 0 skipped；不是完整业务迁移/恢复 | `.superpowers/delivery/postgresql-contracts-0eedc80.log` |
| Work CI | SUCCESS；全栈、独立合同、Dashboard、真 PG、linux/amd64 镜像构建与无网络 smoke | <https://github.com/happykkAi/work/actions/runs/36694198821> |
| Desktop / CodeQL | SUCCESS | runs `36694198770` / `36694198803` |
| 标准 CI | Linux 成功；Windows 2 failed / 3842 passed / 125 skipped / 9 warnings，已本地修复但必须复验 | <https://github.com/happykkAi/work/actions/runs/36694198779> |
| 新发行包/Windows 定向 | exit 0；7 passed / 42 subtests；提交 hook 4 passed / 2 deselected + 静态检查和 Dashboard 构建 | `.superpowers/delivery/distribution-windows-final.log`、`distribution-commit.log` |
| locale 定向 | exit 0；72 passed；提交 hook exit 0 | `.superpowers/delivery/locale-handoff-final.log`、`locale-handoff-commit.log` |

Work CI 制品使用 PR 实际检查的 merge SHA
`7b3c52ba196cd10a88d92a706e029e1f535a7258`：
`work2-candidate-7b3c52ba196cd10a88d92a706e029e1f535a7258`，
GitHub artifact digest
`sha256:a20af5f4e6de757644ef577896301d09e9c75ad6019be91716ba2a28299a348a`。
包内包含 wheel/sdist、linux/amd64 Docker archive、image identity 和 SHA-256 清单。
这不是新 HEAD 的镜像摘要，也不是当前部署版本；需由最终候选重新生成。

最新上传会触发新的 PR CI。交接时不能将运行中的检查写成通过；接手者须
读取 PR checks 和每个 run 的实际 conclusion。真实模型 live job 在本 fork
按 upstream-only 条件跳过，没有通过真实模型验收。

25 个本地 skips：9 个平台项（3 `/root`，6 Linux/bwrap）、15 个 PG 缺 URL、
1 个独立 Work wheel 缺 artifact 变量。后 16 项在独立 gate 真实执行，
不代表原全量执行没有 skip。13 warnings：Lark 8、websockets/uvicorn 4、
Discord audioop 1；ESLint 67 warnings 和 jsdom/Vite 诊断另算，不笼统标为无影响。

独立差异审查曾发现 2 Important / 1 Minor，上表已修复；最终差异仍需复审。
CodeRabbit 全分支审查因免费计划 150 文件限制而退出 1（实际 192 文件），
不是“零问题”，不购买服务，也不以另一种审查替代它的实际结果。

## 4. 发布阻断及部署状态

| 门槛 | 当前实际状态/缺口 |
| --- | --- |
| 旧 Work → Work2 | 合成历史保全/重复执行/中断续导已演练；实际 MariaDB 源转换、身份/旧密码映射、业务激活、历史会话和文件在 UI 可访问尚未完成 |
| 业务闭环 | 尚未完成登录→正确机构/项目→任务→执行→保存→刷新恢复→重新打开；项目、成果、复核等承诺能力存在实现缺口，不是凭据问题 |
| 文件成果与两机构隔离浏览器验收 | NOT_RUN；不能拿 HTTP 200、管理员页面或 stub 回复替代 |
| 上游旧版本→候选升级 | NOT_RUN；机构 runtime A/B 不等于软件 A→B 升级 |
| 两类业务恢复 | 无新增写入回退、已有新增成果后的停写/增量保全/兼容恢复均未验收；PG backup/restore 用例不能替代 |
| 最终新 SHA 全量与审查 | NOT_RUN/CI 待确认；新修复后必须重新绑定源码、锁、镜像、配置和迁移版本 |
| 受控预发 / 生产 | 未部署、未放行。最新用户选择独立测试入口，旧 Work 不动；随后要求本轮先上传交接 |

当前 `project_id=None`、`allowed_asset_versions=frozenset()`，项目能力在现有
地图中为 Planned，部分 projects/results/legacy/runs 业务路由尚无实现。
不得用新建一个不同产品、全拒绝请求或放宽权限冒充这几项通过。

GitHub 已创建 `work2-preproduction` / `work2-production` environments，
但尚无保护规则、分支策略、部署凭据或 Work2 部署 workflow。没有复制
具有 Hub 权限的 SSH 私钥。旧部署通道位于 `happykkAi/shegongai-agent-lab`
的 `deploy-ucloud.yml`，是 Node/MariaDB/Drizzle，不能原样部署 Work2。

服务器只读检查：x86_64，Docker 29.1.3，未安装 Compose；无 `/etc/work2`
或 `/opt/work2`；当时约 1.6 GiB 可用内存、6.2 GiB 剩余磁盘。未修改旧
服务、数据库、Nginx、DNS 或 Hub。没有执行备份导出、生产迁移或切换。
旧本地 entry/A/B lab 仍是 `work2-local:final-fixed-20260930`，不能引用为
新 shared-authority 候选的环境验收。

## 5. 接手运行入口

先回读远端和脏工作区，保全修改，不 reset/force push：

```sh
git status --short
git fetch origin
git log -5 --format='%H %s'
gh pr view 1 --repo happykkAi/work
gh pr checks 1 --repo happykkAi/work
```

本机锁定工具目录（`uv-0.12.19` 是目录，需使用其中 `uv`）：

```sh
WORK2_TOOLS='/Users/happy/Documents/Codex/2026-09-28/work2-octop/candidate/happykkAi-work-232030f/.superpowers/sdd/Work2_Octop_完整替换与持续升级计划_20260927/tools'
export PATH="$WORK2_TOOLS/uv-0.12.19:$WORK2_TOOLS/node-v24.21.0-darwin-arm64/bin:$PATH"
uv lock --check
uv lock --project packages/work_platform --check
uv sync --frozen --python 3.12.13
uv sync --project packages/work_platform --frozen --python 3.12.13
npm ci --prefix dashboard --no-audit
make check-all PYTEST_JOBS=4
(cd dashboard && npm test -- --run --maxWorkers=2)
```

真实 PG 串行 gate 见 `.github/workflows/work-ci.yml` 的 `postgres` job；
只允许专用测试数据库 schema reset，不能连接或清空生产/现有 lab 私有库。
本机 Docker socket：`unix:///Users/happy/.colima/default/docker.sock`。
测试凭据只从已保存的环境/本地受限文件读取，不打印，不放入 Git。

分发入口：`tests/unit/work/test_octop_distribution.py`、
`tests/work_contracts/test_distribution.py`、`tools/work/verify_distribution.py`。
role provisioning：`tools/work/provision_control.py`；历史保全：
`tools/work/import_legacy.py`。完整实施记录在
`docs/work2-delivery-2026-09-30.md`。

`deploy/work/build-manifest.json` 已标注为历史本地候选、不匹配当前源码。
不得为了填 `work_sha` 修改历史证据，最终 manifest 由实际新构建生成。
本地 `.superpowers/` 原始证据未提交到公共仓库，路径均相对正式工作目录；
接手另一台机器时优先读 GitHub CI，需要本地证据时走安全传递，不上传
原始敏感日志、生产导出、凭据或用户正文。

继续交付时保持既有授权与门槛：可分阶段修复、提交、推送和 PR；只有各自
门槛通过后才合并/预发/生产。真实供应商测试还需已有授权预算的具体边界，
未提供模型/次数，不能擅自付费调用。不得删除旧库、卷或恢复材料。
