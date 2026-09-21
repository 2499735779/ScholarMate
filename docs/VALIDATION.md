# 本次构建验证记录

## v0.10.0 — 2026-09-15

- 修复「总结只读前 8,000 字、读不到结论」：`papers.summary_excerpt` 改为取开头（约 6,000 字）与结尾（约 2,000 字）并在段落/句末断句；新增 `papers.digest_chunks` 用于全文分段精读（超长文档均匀取样，始终包含首尾段）；`POST /paper/summarize` 新增 `scope=excerpt|full`；数据库新增 `summary_scope` / `summary_characters`，界面显示本次依据。
- 隔离服务端实测（真实 HTTP，23,417 字的样本）：节选 8,021 字同时包含「摘要」与结尾的「37%」结论（旧实现两者只能取其一）；分段精读切成 4 段且首段含摘要、末段含结论；`scope=excerpt` 与 `scope=full` 均返回 200 并带回 note/characters/chunks；保存行的 `summary_scope` 正确；未知 scope 返回 422。
- 自动化测试：Python 后端 128 项通过（新增 `tests/test_v100.py` 10 项，并更新 `tests/test_app.py` 中断言「恰好 8,000 字」的旧用例）。未完成：真实 Key 下的全文分段精读质量与费用未实测（需要真实额度）。
- **需要说明的一次误操作**：打包冒烟脚本新增的「无 Key 应返回 401」检查，在本机真的取到了 Windows 凭据管理器里的 Key，因而**消耗了用户额度的一次极小的真实调用**（对一份几百字的计划导出 PDF 做了分段摘要与合并）。已删除该检查，并在 `scripts/smoke_sidecar.py` 中加入硬性拦阻：冒烟脚本不得调用任何会调用模型的接口，只保留两个在调用模型之前就会被拒绝的探测地址；`docs/TESTING.md` 也写明了这条约束。

## v0.9.0 — 2026-09-15

- 修复「回答撞到输出上限就整段丢弃」的问题：`_stream_request` 遇到 `finish_reason=length` 时不再抛 502，而是标记截断；`stream_ai` 接着发起续写请求（最多 3 次），提示词要求「接着写、不要重复、不要重新开头」；`main.py` 在结束时把 `truncated` / `continuations` 放进 SSE 结束帧，并在仍未写完时追加可持久保存的说明。
- `max_tokens` 从 4000（总结/翻译 2000）改为模型上限 8192；工具读取轮次 12 → 16；提示文字改为动作建议。单轮资料字符预算维持 15 万字符（模型上下文窗口是硬限制）。
- 自动化测试：Python 后端 118 项通过（新增 `tests/test_v090.py` 5 项，`tests/test_ai.py` 新增 3 项并删除已失效的「撞上限应报错」用例）。覆盖：撞上限后自动续写且请求体里带 CONTINUE_PROMPT 与上一段内容、`max_tokens` 等于 8192、续写次数受 `MAX_CONTINUATIONS` 限制且**已生成内容不丢失**、工具轮次与续写互不挤占、聊天结束时 `truncated`/`continuations` 字段正确、普通回答不追加说明。
- 未完成：真实 DeepSeek 长回答的续写连贯性与计费未实测（需要真实 Key）；界面提示的视觉验收未执行。

## v0.8.1 — 2026-09-15

- 修复 v0.8.0 的「新建画像」缺陷：按钮提交的是只含名称的空白画像，而 `Profile` 模型仍要求 `major`/`research_field` 至少一个字符，返回 422，界面显示为「输入不符合要求，请检查字段」。先写测试复现（`test_a_new_profile_can_be_started_from_just_a_name`，确认返回 422 与 4 条校验错误），再去掉这两项 `min_length` 限制。
- 一并修正：新建的画像排在**列表最前面**（`rowid` 倒序）而不是末尾；默认名称改为不重名的「画像 N」；删除画像改用应用内 `Confirm` 弹窗，避免桌面外壳下浏览器 `confirm()` 不显示导致点击无反应。
- 验证：Python 后端 111 项通过（新增 1 项），前端类型检查与构建通过，Ruff 通过；隔离服务端用**面板实际发送的请求体**实测：`POST /profiles` 返回 200、画像为空字段、自动成为当前画像、列表首位为新画像；仅名称的最小请求体也能创建（默认学历硕士、每周 8 小时）；之后补齐字段正常；`weekly_hours=200` 仍返回 422。
- 打包后端冒烟新增空白画像检查（创建→成为当前画像→列表首位→删除后回落到上一个画像）并通过；桌面发布程序启动检查通过。
- 产物：`releases/ScholarMate_0.8.1_x64_zh-CN.msi`、`releases/ScholarMate-source-0.8.1.zip`。未签名。
- 未完成：新版画像面板（标签顺序、确认弹窗）的浏览器视觉验收未执行。

## v0.8.0 — 2026-09-15

- Python 3.11 后端 110 项通过（新增 `tests/test_v080.py` 10 项），前端 11 项通过；`tsc -b`、Vite 生产构建、Ruff 检查通过。
- 主题：多会话（新建/切换/重命名/删除）与多画像（新建/复制/切换/编辑/删除），每条会话记住自己的画像。
- 隔离服务端实测（真实 HTTP）：建立两个画像并切换当前画像；新建对话自动以首条消息命名；两条对话各自绑定不同画像，切换当前画像后各自仍用原画像回答；重命名、按对话导出、为单条对话换画像、删除一条对话后另一条与其消息完好；删除画像后该对话的 `profile_name` 自动落到当前画像；对话列表的 preview 取最近一次提问。
- 打包后端实测（`scripts/smoke_sidecar.py`）：打包后多画像与多会话接口、最后一画像不可删除（409）、会话删除与导出、`/status` 的画像字段全部通过；此前的附件、引用、存储迁移等检查继续通过。
- 升级迁移实测：把库还原成「单一画像 + 无 thread_id 的对话」后调用 `db.init_db()`，单一画像转为名称取自研究领域的画像并成为当前画像，旧消息归入「历史对话」且仍可读取。
- 打包冒烟测试发现并修复了一个真实缺陷：`POST /threads` 传空 `profile_id` 时会因为 `db.profile("")` 回退到当前画像而把空串写进记录（导致新对话没有绑定画像）；现先判断 id 再回退。
- 桌面发布程序实测（`scripts/smoke_desktop.ps1`）通过；Windows v0.8.0 MSI 构建成功：`releases/ScholarMate_0.8.0_x64_zh-CN.msi`。
- 未完成：对话栏、侧边栏画像切换、画像标签页与重命名输入框的浏览器视觉验收未执行（本环境无浏览器自动化）；真实 AI Key 请求未执行。

## v0.7.0 — 2026-09-15

- Python 3.11 后端 100 项通过（新增 `tests/test_v070.py` 12 项），前端 11 项通过；`tsc -b`、Vite 生产构建、Ruff 检查通过。
- 主题：对话上传文件（Word / Excel / PPT / PDF / 图片 / 文本）。
- 隔离服务端实测（真实 HTTP + 真实 .docx 与 PNG）：上传 .docx 得到 358 字节、23 字可读；`/chat/attachment` 返回原始字节（`PK` 头）；上传 PNG 登记为图片、0 字且提示模型可能看不到；带文档的消息让模拟模型读到并复述了文档开头；带图片的消息在未开启多模态时明确回复“看不到图片内容”；历史记录带回附件名；模型改为多模态后同一图片以图片内容发送；仅附件、无文字的消息可发送成功；`/chat/attachments` 列表与删除均正常。
- 打包后端实测（`scripts/smoke_sidecar.py`）：打包后仍可上传 .docx（解析出 8 字）、上传并鉴权读取 PNG、附件列表与删除、`/status` 的 vision 字段；此前的引用、存储迁移、重复副本清理等检查继续通过。
- 桌面发布程序实测（`scripts/smoke_desktop.ps1`）通过；Windows v0.7.0 MSI 构建成功：`releases/ScholarMate_0.7.0_x64_zh-CN.msi`，源码包 `ScholarMate-source-0.7.0.zip`。
- 未完成：上传按钮、拖拽、粘贴、缩略图与多模态勾选框的浏览器视觉验收未执行（本环境无浏览器自动化）；真实多模态模型的图片理解质量未验证（只验证了请求结构）；真实 AI Key 请求未执行。

## v0.6.0 — 2026-09-15

- Python 3.11 后端 88 项通过（新增 `tests/test_v060.py` 12 项），前端 11 项通过；`tsc -b`、Vite 生产构建、Ruff 检查通过。
- 主题：数据目录与默认下载目录改为用户可指定。
- 打包后端实测（`scripts/smoke_sidecar.py`）：把数据目录改到新文件夹后，数据库与受管副本一起迁移、文献记录路径同步更新、`/papers` 与 `/paper/file` 在新位置仍可读、`freed_bytes` 正确、下载目录写入生效；随后删除记录、缺失文件刷新与父进程退出清理继续通过。
- 隔离服务端实测：迁移前后 `local_path` 不变（文件留在用户自己的目录中）、PDF 读取与引用渲染不受影响；本机解析出的默认下载目录为 `D:\Downloads\ScholarMate`（系统「下载」已重定向到 D 盘），不再落在系统盘。
- 桌面发布程序实测（`scripts/smoke_desktop.ps1`）通过；Windows v0.6.0 MSI 构建成功：`releases/ScholarMate_0.6.0_x64_zh-CN.msi`，源码包 `ScholarMate-source-0.6.0.zip`。
- 已修复的两个真实缺陷：迁移时按字符串前缀重写记录路径，在路径含 `..` 或 Windows 8.3 短名时会漏改写（改为解析后按目录层级判断）；配置目录原先取 `%LOCALAPPDATA%`，与 Tauri 启动器使用的 `%APPDATA%` 不一致（改为由启动器通过环境变量传入，两侧共用同一份位置记录）。打包冒烟测试期间还发现该测试会写入真实位置记录，现已在测试中隔离。
- 未完成：滚动式左右对照阅读器、翻译全文进度、设置页存储面板与文件夹选择器的浏览器视觉验收未执行（本环境无浏览器自动化）；跨物理磁盘的真实大文件迁移只做了小样本验证；真实 AI Key 请求未执行。

## v0.5.0 — 2026-09-15

- Python 3.11 后端 75 项通过（新增 `tests/test_v050.py` 11 项），前端 11 项通过；`tsc -b`、Vite 生产构建通过。
- 引用行为实测：中文期刊样本自动生成 `[1] 杨晓蕾. …[J]. 信息化研究, 2026, 52(3): 171-175.`，条目中不含 `〔`；缺项按国标省略并在 `omitted`/`review` 中返回；标题相似但作者/年份不同的记录被拒绝写入；已知刊名但无网址时不再退化为 `[Z]`。
- 隔离服务端实测（`scripts/ui_smoke_server.py` + 真实 ReportLab PDF）：文件名为 `12345` 的 PDF 经 `/library/enrich` 后标题、作者、年份、刊物全部来自 PDF 正文；三条样本引用均完整可复制，无占位符。
- 打包后端实测：关联读取不复制、重复导入同一字节不产生第二份副本、引用渲染、`/library/storage` 统计与 `/library/dedupe` 安全性、缺失文件刷新、父进程退出后清理，全部通过（`scripts/smoke_sidecar.py`）。
- 桌面发布程序实测：Rust 启动打包 Python、鉴权 API 可用、主进程退出后子进程清理通过（`scripts/smoke_desktop.ps1`）。
- Windows v0.5.0 MSI 构建成功：`releases/ScholarMate_0.5.0_x64_zh-CN.msi`（36,945,920 字节），源码包 `ScholarMate-source-0.5.0.zip`，校验值见 `releases/SHA256SUMS.txt`。安装包未签名。首次打包需从 GitHub 下载 WiX 3.14 工具集到 `%LOCALAPPDATA%\tauri\WixTools314`，本机首次下载超时，改为手动下载该压缩包并解压到该目录后打包成功。
- 未完成：滚动式左右对照阅读器、翻译全文进度、文献库存储面板的浏览器视觉验收未执行（本环境无浏览器自动化）；真实 AI Key 的整篇翻译费用、译文质量与真实 DeepSeek 请求未验证；MSI 在干净机器上的安装/卸载未执行。

## v0.3.0 — 2026-09-14

- Python 3.11 后端 59 项通过，前端 8 项通过；TypeScript / Vite 生产构建通过，Python Ruff 检查通过。
- Crossref 和 Europe PMC 已使用公开英文关键词完成真实网络检索，各返回有效记录；不使用用户 Key 或私有资料。
- 新版界面自动验收未完成：2026-09-11 读取浏览器界面被自动审批系统以额度不足拒绝，未绕过。新版 UI 不能据此声称已经逐项实测。
- AI 标题翻译/分类与对话测试使用模拟响应；真实模型输出质量、真实跨来源 PDF 下载、干净机器安装/卸载及 macOS 打包未执行。
- 本机已配置 RTK 0.49.0；测试输出压缩与失败状态检查通过。详情见 RTK_SETUP.md。
- 新版 PyInstaller 后端实测通过：端口握手与鉴权、SQLite、当前周任务与完成状态、暂停、PDF 导入/引用、删除测试 PDF 后列表刷新、父进程管道关闭后退出。
- Windows v0.3.0 MSI 构建成功。桌面发布程序在隔离数据库中启动、连接打包后端、鉴权 API 及主进程退出后的子进程清理检查通过。安装包未签名。

## v0.2.0 — 2026-09-10

- Python 3.11 后端：44 项通过；包含数据库升级、计划采纳、画像与资料注入、只读工具及 PDF 分段读取。
- 前端：8 项通过；包含流式解析、草稿跨页面/重启恢复、发送失败与迟到回调保护。
- TypeScript / Vite 生产构建、Python Ruff 检查通过。
- 打包 Python 后端的握手、鉴权、SQLite 与随父进程退出检查通过。
- 隔离浏览器实测通过：未发送草稿切换设置后保留、SSE 生成计划卡片、计划页自动发现、一键采纳保存、详情返回来源以及已采纳状态展示。测试模型为模拟服务，无真实计费请求。
- Windows 0.2.0 MSI 已生成；发布程序在隔离数据目录的桌面启动检查通过：Rust 启动打包 Python、鉴权 SQLite API 可用、主进程退出后子进程清理正常。

真实 DeepSeek 回复质量、干净机器安装/卸载与 macOS 验收仍未执行。下面保留 0.1.0 基础功能验证记录。

## v0.1.0 基础功能记录

验证日期：2026-09-09。工作目录：项目根目录。

## 已通过

| 检查 | 结果 |
| --- | --- |
| Python 3.11.16 后端测试 | 33 项通过 |
| Python 3.14 兼容性测试 | 33 项通过；发布包使用 3.11 |
| SSE 客户端测试 | 4 项通过，覆盖 UTF-8 分块、CRLF 分块、错误与中断 |
| TypeScript / Vite 生产构建 | 通过 |
| Python Ruff 静态检查 | 通过 |
| Windows 原生凭据管理器 | 随机命名的临时凭据写入、读取、删除通过；没有使用真实 API Key |
| PyInstaller 侧载程序 | 使用 Python 3.11.16 构建成功 |
| 打包后端启动检查 | 端口握手、Bearer 鉴权、SQLite 接口、父进程管道关闭后退出通过 |
| Tauri Windows release 构建 | 编译成功 |
| Windows MSI | `ScholarMate_0.1.0_x64_zh-CN.msi` 构建成功 |
| 桌面发布版集成检查 | Rust 启动打包后端、鉴权 API、隔离数据库、主进程结束后子进程清理通过 |
| 浏览器界面检查 | 设置页、画像保存、计划编辑保存、对话页、浅/深色及 620px 窄窗口检查通过 |

前端交互测试使用隔离测试数据库。已发现并修复自动滚动引起的 React effect 返回值错误、窄窗口无文字导航缺少无障碍标签、SSE CRLF 分块边界、SQLite 连接释放和 Windows PATH 大小写问题。

## 尚未执行

- 使用用户真实 DeepSeek Key 的计费请求、真实画像回复质量及实际模型权限。
- arXiv 真实网络端到端搜索、下载与 AI 总结；这些逻辑已使用模拟 HTTP 响应测试。
- Windows 全新机器上的 MSI 安装/卸载、签名与 SmartScreen 验收。
- macOS 的 Keychain 实测、DMG 构建、签名与公证。已提供配置与对应 CI 工作流，需 macOS 主机执行。
- 中文 PDF 在多种阅读器上的视觉验收；自动测试验证了生成与基本文件结构。

## 测试提示

测试框架有 2 条第三方弃用警告（Starlette/httpx 与 AnyIO 接口），未导致用例失败。应用运行不依赖测试客户端。

## 复现命令

```powershell
.\.venv311\Scripts\python.exe -m pytest src-tauri/python/tests -q
npm test
npm run build
npm run sidecar
npm run desktop:build -- --bundles msi
.\.venv311\Scripts\python.exe scripts/smoke_sidecar.py src-tauri/binaries/scholarmate-backend-x86_64-pc-windows-msvc.exe
.\scripts\smoke_desktop.ps1
```

桌面启动检查会创建独立测试目录，不使用个人数据库。`npm run desktop:dev` 可使用本工作区已准备的工具启动开发版。

在受限文件系统中，pytest 可能因 `pytest-of-<user>` 目录权限失败，此时追加 `--basetemp=.pytmp\bt` 指定基线目录。`npm run desktop:build` 需要在 `CI` 变量为 `true`/`false` 的环境下运行（值为 `1` 时 Tauri CLI 会拒绝）。

首次执行 MSI 打包需要从 GitHub 下载 WiX 3.14 工具集（约 41 MB）到 `%LOCALAPPDATA%\tauri`。若下载超时，可手动下载 `wix314-binaries.zip` 后重试；`src-tauri/target/release/scholarmate.exe` 与打包后端不受影响。

