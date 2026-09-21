# ScholarMate

当前版本：**0.10.0**。本轮修正论文总结：默认改为读**开头与结尾**（含摘要与结论，旧的「前 8,000 字符」读不到结论），并新增「总结全文（分段精读）」覆盖方法与结果正文。此前版本已提供长回答自动续写、多会话与多画像、对话上传文件、存储位置自定义、打开即自动生成的国标引用与沉浸式左右对照阅读。使用方式见 `docs/QUICKSTART.md`，升级说明见 `docs/RELEASE.md`。

Tauri 2 + React 19 + TypeScript + Python 3.11 学术桌面应用。依据《产品需求文档》实现 Phase 1–6；产品名按本次请求使用 ScholarMate。前端提供 Shadcn/ui 风格的本地 Button/Input 组件（Radix Slot + CVA），其余表单为可访问的原生控件。

## 项目结构

```text
src/                       React 页面、布局、流式客户端、UI 组件
src-tauri/src/main.rs       Python 生命周期、启动握手、系统导出窗口
src-tauri/python/           FastAPI、SQLite、凭据管理、AI、arXiv、PDF
src-tauri/python/tests/     模拟 API 与本地数据测试
src-tauri/tauri.conf.json   窗口、安全策略与安装包配置
scripts/                   Python 侧载打包脚本与图标源文件
docs/                      内置帮助、发布说明与测试清单
```

## 环境准备

新克隆的工作区需要先按下方步骤安装依赖和工具链，然后运行 `npm run desktop:dev` 启动桌面开发版。`npm run sidecar` 会自动选择已准备的 Python 环境；`npm run desktop:build -- --bundles msi` 构建 Windows 安装包。这些包装命令也兼容其他机器的系统工具链。

Windows 安装 Node.js 22 LTS 或更新版本、Python 3.11、Rust stable（包含 Cargo）、Microsoft C++ Build Tools 的桌面 C++ 工作负载，以及 WebView2 Runtime。macOS 安装对应版本的 Node/Python/Rust 及 Xcode Command Line Tools。建议使用 Python 3.11 进行发布构建。

### Windows PowerShell

```powershell
cd ScholarMate
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r src-tauri/python/requirements.txt
npm ci
npm run tauri icon scripts/icon.svg
.\.venv\Scripts\python.exe scripts/build_sidecar.py
npm run tauri dev
```

### macOS

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r src-tauri/python/requirements.txt
npm ci
npm run tauri icon scripts/icon.svg
.venv/bin/python scripts/build_sidecar.py
npm run tauri dev
```

首个 sidecar 构建为 Tauri 的 externalBin 文件检查提供对应平台文件。开发运行时 Rust 实际启动 `.venv` 内 Python；发布运行时使用 PyInstaller 单文件程序，最终用户无需安装 Python。Python 依赖变更后重新构建 sidecar。

## 仅运行前后端预览

不具备 Rust 时仍可运行完整业务界面：一个终端运行 `.venv` 内 Python 的 `src-tauri/python/main.py`，另一个运行 `npm run dev`。打开 `http://127.0.0.1:1420`，把 Python 启动输出的 `port` 与 `token` 填入连接页。令牌仅限本地开发，不要分享。后端重启后需重新填写连接信息；可清空该页面的 sessionStorage。

## Phase 1 基础与画像

- `db.py` 的 SCHEMA 包含 user_profile、settings、conversations、learning_plans、papers 创建语句；启动自动初始化，WAL 模式。后续变更表结构需新增迁移，本版本为初始 schema。
- `security.py` 显式选择 Windows/macOS 原生 keyring，禁止明文回退。`get_key()` 仅供 Python 内部调用，没有返回明文 Key 的 HTTP 接口。
- `GET /status` 返回 Key/画像是否存在及模型名；`PUT /settings` 保存 Key 和模型；`POST /settings/test` 验证；`GET/PUT /profile` 读写画像。
- 默认入口缺少 Key 或画像时进入设置；其他导航保留本地离线数据访问能力。

## Phase 2 统一 AI 与对话

- `ai.call_ai(task_type, user_message, context=None)` 将同一个真实流式核心聚合为字符串。所有智能任务都使用该核心，按 chat/plan/summarize/translate 模板选择任务，注入完整画像。
- `POST /chat` 使用 fetch POST SSE（支持 Authorization 请求头），返回 delta/done/error。真实模型增量输出；非打字机模拟。
- 成功的用户/助手消息成对事务保存，多轮自动带最近 20 条且限制历史字符预算。失败/取消不保存本轮；单会话锁防止混乱。
- `GET/DELETE /conversations` 查看/清空；`GET /conversations/export` 导出 Markdown。
- 连接和读取超时、最多 3 次重试；已输出内容后不重试，避免重复。401/余额/限流/上下文超限映射为友好错误。

## Phase 3 学习计划

`POST /plans/generate` 生成；`GET/POST /plans` 列表/新增；`GET/PUT/DELETE /plans/{id}` 详情/修改/删除；`GET /plans/{id}/export?format=md|pdf` 导出。Markdown 编辑器采用轻量双模式 textarea + react-markdown/GFM，支持编辑与预览。未保存修改时禁用导出。PDF 使用 ReportLab，无需 GTK/Pandoc；排版范围见 FAQ。

## Phase 4 文献

`GET /papers/search?keyword=...` 相关性搜索；`POST /papers/download` 返回进度 SSE，下载完成写元数据；`GET /papers?q=...` 本地查找；`GET/DELETE /paper?id=...` 详情/删除。旧版带斜杠的 arXiv ID 使用查询参数传递，文件名安全转换。只允许 arXiv HTTPS PDF 地址及受限重定向、100 MB 上限、临时文件完成后重命名；拒绝覆盖已有文件。批量下载逐个执行，每篇失败独立报告。

## Phase 5 总结和翻译

`GET /paper/text?id=...` 提取文本，处理扫描、加密与损坏 PDF；`POST /paper/summarize?id=...` 默认提取开头与结尾节选，或使用 scope=full 分段精读，并保存 summary；`POST /paper/translate` 翻译指定文本；`POST /paper/translate-page` 按页返回逐块译文，供阅读区左右对照；`POST /paper/folder?id=...` 打开已记录 PDF 所在目录。解析放到线程池，避免阻塞 SSE。

## Phase 12 论文总结范围（v0.10.0）

- `papers.summary_excerpt(text, budget)` 返回论文开头（约 75% 预算）与结尾（约 25% 预算），切分点回退到段落或句末，中间用标记说明省略；这正是旧实现 `text[:8000]` 读不到结论的修正。
- `papers.digest_chunks(text, budget=7000, limit=14)` 按段落打包成分段；超出上限时在全文范围均匀取样，并强制包含第一段与最后一段。`ai.DIGEST_BUDGET` / `ai.DIGEST_LIMIT` 控制参数。
- `POST /paper/summarize?id=...&scope=excerpt|full`：`excerpt` 单次调用（系统提示说明只提供首尾并允许用工具补读）；`full` 先对每段调用 `ai.call_ai("digest", ...)`（`isolated` 上下文），再把要点合并成最终总结。结果写入 `summary` / `summary_scope` / `summary_characters`。

## Phase 11 长回答续写（v0.9.0）

- `ai.MAX_OUTPUT_TOKENS = 8192`：`max_tokens` 取模型单次输出上限（只是上限，按实际生成计费）。`ai.MAX_CONTINUATIONS = 3` 控制一次请求内最多续写几次，`MAX_ROUNDS = 16` 是工具轮次与续写轮次共享的预算。
- `_stream_request` 遇到 `finish_reason="length"` 只标记截断，不再抛错；`stream_ai` 在无工具调用时把已生成内容与 `CONTINUE_PROMPT` 追加进消息后继续请求，并把 `truncated` / `continuations` 写回调用方的 context。
- `POST /chat` 在结束帧返回 `truncated` 与 `continuations`；仍未写完时追加 `ai.TRUNCATED_NOTE` 到助手消息，因此结论会随消息一起持久保存。

## Phase 10 多会话与多画像（v0.8.0）

- `profiles` 表保存多个学术画像，`settings.active_profile_id` 指向当前画像；`db.profile()` 返回当前画像（可传入 id 取指定画像），旧版单行 `user_profile` 在首次启动时自动转成第一个画像（名称取研究领域）。
- `chat_threads` 保存多条对话，`conversations` 增加 `thread_id` / `profile_id`；旧版扁平记录在首次启动时归入「历史对话」。`GET/POST /threads`、`GET/PUT/DELETE /threads/{id}`、`GET /threads/{id}/export` 提供新建、切换、重命名、改画像、删除与按对话导出。
- `POST /chat` 接受 `thread_id`：不存在时自动新建并用首条消息命名，SSE 结束帧返回该对话；`ai.build_messages` 只回放该对话的历史，并使用会话自己的画像（`context["profile"]`），因此切换当前画像不会改变已有对话的方向。
- `GET/POST /profiles`、`PUT/DELETE /profiles/{id}`、`POST /profiles/{id}/activate` 管理画像；删除画像时其对话自动改绑当前画像，最后一个画像不可删除。

## Phase 9 对话附件（v0.7.0）

- `POST /chat/upload` 接收 base64 文件，按扩展名与文件头双重校验；`attachments.py` 在本机解析 Word（word/document.xml）、Excel（sharedStrings + 工作表行）、PowerPoint（a:t 段落）、PDF（pypdf）与文本（多编码回退），解析结果写成同名 `.txt` 供工具分页读取；图片只登记不解析。
- 相同字节复用同一条附件记录（`at-<sha256 前缀>`），文件存放在数据目录的 `uploads/`，随数据目录迁移；`GET /chat/attachment` 鉴权读取原文件，`DELETE /chat/attachment` 同时删除登记与文件。
- `POST /chat` 可带 `attachments`：文档文字随消息内联（单文件 6,000 字、超出部分由工具补读），图片在 `settings.vision` 打开时以 OpenAI 兼容的 `image_url` 内容发送，否则在提示里说明模型看不到图片。对话记录新增 `attachments` 列保存附件 id。
- `read_workspace` 新增 `attachment` 动作（8,000 字分页），工作区快照附带最近 10 个附件索引；图片附件返回「没有可提取文字，不要编造」。
- 设置新增 `vision` 字段：未显式设置时按模型名（vision / omni / gpt-4o 等）推断，显式值优先。

## Phase 8 存储位置（v0.6.0）

- `paths.py` 决定数据目录与默认下载目录：优先 `SCHOLARMATE_DATA_DIR`/`SCHOLARMATE_CONFIG_DIR` 环境变量，其次配置文件 `storage.json`（位于操作系统配置目录，Windows 为 `%APPDATA%\com.scholarmate.desktop`），最后是平台默认目录。指定盘符未挂载时回退默认目录，避免把数据写到不可预期位置。
- Rust 启动器把 Tauri 的 `app_config_dir` 通过环境变量传给 Python，并从中读取用户选择的数据目录，两侧共用同一份记录。
- `GET /settings/storage` 返回当前与默认的两个路径、占用字节与系统盘符；`PUT /settings/storage` 可设置或重置它们。更改数据目录会把数据库与 `<data>/papers` 复制到新位置并逐文件校验大小，成功后才删除原文件，随后同步更新记录中的受管副本路径；失败则整体回滚。
- 默认下载目录为系统「下载」文件夹下的 `ScholarMate` 子目录，`papers.download_pdf` 在请求未指定目录时使用它。

## Phase 7 引用、阅读与磁盘占用（v0.5.0）

- `GET /paper/citation` 只用已确认字段渲染 GB/T 7714-2015 条目，未知要素按国标省略并在 `omitted`/`review` 中返回，任何情况下都不写占位符。`POST /paper/citation/resolve` 先读 PDF 首页与页脚，再按 DOI 或精确标题查询 Crossref、OpenAlex、Europe PMC、arXiv、DataCite；只有标题完全一致且作者/年份相容的记录才会写入，写入后标记 `citation_checked`，避免重复联网。
- `enrich` 的模型回答只作为候选：标题、作者、年份、刊物必须在 PDF 正文中逐字出现才会写入数据库，否则保留原文件名。
- `GET /library/storage` 返回应用数据目录、应用下载目录、关联文件数量与实际副本字节数；`POST /library/dedupe` 按字节比对应用旧导入目录中的副本与用户目录（下载、文档、桌面、`~/ScholarMate`）中的同名文件，确认后才删除副本并改为关联原文件。清理范围固定为应用自己创建的副本。
- 阅读器为前端实现：PDF.js 连续滚动、按需渲染、离开视口释放位图；「翻译全文」逐页调用 `translate-page`，译文覆盖在右侧同一页的原文字位置，PDF 文件与排版不变。中文文献自动识别后不提供翻译。

## Phase 6 安全、测试与发布

- 仅监听 127.0.0.1，OS 分配端口，每次进程启动生成随机 token；全部路由需 Authorization Bearer。桌面通过受限 Tauri 命令获取握手，Key 不参与握手。
- CORS 白名单仅开发端口和 Tauri 源，不允许 `*`；CSP 仅允许本机后端请求。所有云端请求从 Python 发起，因此无需为 DeepSeek/arXiv 开放浏览器跨域。
- macOS Info.plist 仅允许本地网络 HTTP，云端接口继续使用 HTTPS。
- Rust 启动后端时传入 Tauri 用户应用数据目录（`com.scholarmate.desktop`），开发预览则使用 platformdirs 的 ScholarMate 目录。两种方式默认数据库位置不同。可用 `SCHOLARMATE_DATA_DIR` 显式指定测试/开发目录。
- 关闭窗口退出时终止 Python；父进程管道断开也会退出。密钥与令牌不写文件、不打印请求日志。
- Markdown 不执行 HTML，不渲染远程图片，避免论文内容发起非预期资源请求。

```powershell
.\.venv\Scripts\python.exe -m pytest src-tauri/python/tests -q
npm test
npm run build
.\.venv\Scripts\python.exe scripts/build_sidecar.py
npm run tauri build -- --bundles msi
```

`scripts/smoke_sidecar.py <打包后的后端可执行文件>` 会在临时数据目录中启动已打包的服务，检查握手、鉴权、关联读取不复制、引用渲染无占位符、存储统计与重复副本清理的安全性，然后关闭进程。

macOS 用 `.venv/bin/python` 构建 sidecar，再运行 `npm run tauri build -- --bundles dmg`。产物位于 `src-tauri/target/release/bundle/`。不能在 Windows 直接构建 macOS DMG，需各平台分别构建。详见 `docs/RELEASE.md` 与 `docs/TESTING.md`。

## 官方接口参考

- Tauri sidecar: https://v2.tauri.app/develop/sidecar/
- Tauri CSP: https://v2.tauri.app/security/csp/
- DeepSeek streaming: https://api-docs.deepseek.com/api/create-chat-completion/
- arXiv API: https://info.arxiv.org/help/api/user-manual.html

