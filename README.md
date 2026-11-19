<div align="center">

<img src="frontend/public/assets/formatly-mark.png" width="88" height="88" alt="Formatly logo">

# Formatly

**毕业论文与实习报告格式检测工具**

[Python 3.11+](#快速开始) · [Vue 3](frontend/README.md) · [TypeScript](frontend/ARCHITECTURE.md) · [MIT License](LICENSE)

[中文](README.md) · [English](README_en.md)

**[快速开始](#快速开始) · [能力范围](#能力范围) · [文档](#文档)**

</div>

Formatly 是一款用于毕业论文和实习报告的格式检测工具，支持纸张大小、页边距、正文字体、字号、行距等检测。用户可上传学校模板和格式说明辅助检测，并在检测后根据报告定位问题，对比要求的格式与实际格式，完成相应修改。

---

## 主要功能

- **按学校要求检测** — 上传学校的论文、实习报告模板和格式说明，核对提取的要求后保存自己的检测方案；不同学校的差异由方案表达。
- **保存与调用多套规则** — 常用格式可通过表单设置，支持方案 JSON 导入导出及匿名样例试跑；学校要求草稿可保存、恢复和丢弃。
- **检查常见格式问题** — 按方案检查 DOCX 的纸张大小、页边距、正文与标题字体字号、缩进、段距、固定或倍数行距、分栏和必需章节。
- **支持常用文件** — 接受 DOCX、PDF、TXT、MD、JSON；各格式可检查的项目见下方能力范围。
- **识别扫描 PDF** — 使用本机 OCR 读取扫描页，识别结果需人工核对。
- **查看检测报告** — 列出问题位置、要求的格式、实际格式和待复核项，可导出 HTML、Markdown、JSON 报告。
- **针对性修复 DOCX** — 勾选可修复的格式问题，生成文档副本并自动复检，可下载修复文档和修改记录。
- **复检与批量处理** — 修改稿关联原检测，按实际证据对照问题变化；同一方案支持批量原稿，逐份查看结果或重试失败项。
- **核对实习材料** — 另支持实习证明检查，以及论文、实习报告和证明之间的姓名、学号、单位、日期核对。
- **浅色与深色模式** — 右上角切换主题，自动保存本机偏好，报告打印保持浅色。

---

## 快速开始

**环境：** Python 3.11+ · Windows / macOS / Linux · 现代浏览器。Node.js 22+ 仅用于前端开发或重新构建资源；扫描 PDF 的自动识别另需本机 Tesseract 及适用语言包。DOCX 可通过 Windows 主机安装的 Word/WPS 只读导出 PDF，见[本机导出说明](docs/office-rendering.md)。

### 1. 安装依赖

在项目根目录执行，以下两组命令按系统选择：

```powershell
# Windows
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```bash
# macOS / Linux；python3 需要为 3.11 或更高版本
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

也可使用 `uv venv` 和 `uv pip install -r requirements.txt` 准备环境。同一份清单在 macOS 和 Linux 上会跳过仅 Windows 的 `pywin32`；Word/WPS 导出仍只在 Windows 上可用。OCR 程序和语言包不会自动下载。正常启动需要完整的 `frontend/dist`，资源缺失时先按[开发与验证](#开发与验证)完成构建。项目从源码目录运行，不安装成 Python 库。

### 2. 启动工作台

```powershell
# Windows
.\.venv\Scripts\python.exe app.py
```

```bash
# macOS / Linux
./.venv/bin/python app.py
```

Windows 可双击 `启动工作台.cmd`。macOS 和 Linux 在项目根目录执行 `sh 启动工作台.sh`。也可以在 PyCharm 中选择项目解释器后运行根目录 `app.py`。启动器优先使用项目 `.venv`。在项目根目录也可以运行 `python -m formatly serve`。

默认监听 **`0.0.0.0:8765`**，健康检查通过后打开浏览器。日志同时打印本机和可用局域网地址：本机使用 `http://127.0.0.1:8765`，其他设备使用 `http://<运行机器IP>:8765`。按 Ctrl+C 停止服务。

| 参数 | 用途 |
| --- | --- |
| `--local-only` | 仅本机访问，绑定 `127.0.0.1` |
| `--no-browser` | 启动服务，不自动打开浏览器 |
| `--host <IPv4>` / `--port 8766` | 指定监听地址或端口 |
| `--data-dir <目录>` | 指定规则、任务与报告的数据目录 |

例如：`.\.venv\Scripts\python.exe app.py --local-only --no-browser`。环境变量 `FORMATLY_HOST`、`FORMATLY_PORT`、`FORMATLY_OPEN_BROWSER` 也可设置启动默认值，显式参数优先；`FORMATLY_OPEN_BROWSER=0` 禁止自动打开，`--open` 可开启。

### 3. 完成第一次检测

1. 选择入口：在“新建检测”选择“预置方案”，选好规则后上传原稿并开始检测。需要本校格式时，改选“学校模板”，上传后核对并保存，再回到预置方案分支检测。已有方案可直接重复调用。
2. 核对文档类型和方案。学校要求涉及局部格式时，按原稿样段确认对应样式或分节，再开始检测；暂不匹配的要求保留人工核对。上传学校材料不是使用预置或已保存方案的前置条件。
3. 在结果页对照问题位置、要求和实际情况，处理人工复核项；可修复项目生成副本并复检，其他修改后重新上传。

“通用论文 · 基础预检”只检查基础项目，不包含本校全部格式要求。“检测完成”表示任务已结束，是否有格式问题需查看检测结果。

学校模板与原稿的范围通过实际样段确认；同一属性在不同明确范围可保存不同要求值，重叠冲突需先处理。学校要求页可配置受支持的标题、题注、参考文献与分节页码结构规则。提取不完整或未支持的条款不能算作通过。

---

## 能力范围

| 格式 | 可检查的内容 | 限制 |
| --- | --- | --- |
| DOCX | 纸张大小、页边距、正文与标题字体/字号、缩进、段距、固定或倍数行距、装订线、页眉页脚距边界、分栏、必需章节和明确字段 | 实际分页、复杂排版及无法确定的属性需要复核 |
| PDF | 实际页面尺寸、可提取文字、标题与字段；明确正文区域内原生文字的字体和字号 | 不反推 Word 样式、行距或页边距；OCR 不证明字体 |
| TXT | 解码文本、独立标题和明确标签字段 | 不承载真实纸张、字体、行距或分页 |
| MD | 文本、标题及明确字段 | 不把 Markdown 显示样式当作打印排版证据 |
| JSON | 普通 JSON 的字符串与字段路径，或结构化文档的标题、段落和字段 | 不补造文件未承载的排版属性 |

结构化 JSON 使用 `formatly.document.v1`，见[文档示例](examples/document.json)与[JSON Schema](examples/document.schema.json)。文档 JSON 与规则方案 JSON 用途不同，不能通过 `profiles import` 把原稿导入为方案。

PDF 正文字体/字号比较需要在方案中明确 `settings.body.pdf_region_mm`，例如 `{"top":30,"bottom":25,"left":25,"right":25}`，单位为毫米。该范围不证明 Word 页边距；未指定时只提供字体清单及复核信息。详见[格式与提取规范](docs/document-formats.md)。

---

## 按学校要求检测

**上传学校模板和说明 → 核对格式要求 → 生成检测方案 → 上传文档检测 → 查看报告并修改**

1. **上传学校要求：** 在“新建检测”选择“学校模板”，按当前文档类型放入学校文件，上传后直接进入核对。同一组里还可以继续添加模板或说明；已保存的要求从侧栏“学校要求”打开。
2. **核对格式要求：** 对照学校文件，逐条核对提取出的要求及数值；要求冲突时选择适用值，不适用的条款需填写排除理由。无法自动检查的要求会列为待复核或不支持。
3. **检测文档：** 确认要求并生成方案后，在第 3 步点击“使用此方案检测”，自动带入方案和文档类型，再上传原稿。方案也保存在“学校要求 → 已保存方案”，可以重复调用；检测页刷新后保留带入的方案。
4. **修复与复检：** DOCX 结果页点击“查看可修复项”，对照位置、实际格式和修复目标勾选问题，再点击“生成副本并复检”。新任务提供修复文档、修改记录和复检报告。其余问题需自行修改，再点击“检测修改稿”上传新文件。“重试本次检测”使用该任务保存的文件和规则。

[论文与报告排版插件](docs/native-plugin.md)提供正文缩进、段距、固定行距、标题与分节参数的内置检查；学校要求确认后可直接编入方案。无法确定的值保留复核，新增属性目前按报告在 Word/WPS 中修改后复检。

针对性修复支持已准确定位的纸张大小、四边页边距、正文字体、字号和倍数行距。仅应用勾选的修改，原文件和历史报告保留；原配对 PDF 不随修复任务沿用。包含保护、签名、修订的文档，以及缺失章节、复杂布局、复杂文字独立字号和无法准确定位的问题不自动修改。旧报告没有定位信息时，需重新检测。各项修改是否满足要求，以新任务的完整复检结果为准。

需要同时核对论文、实习报告和实习证明时，可在“材料核验”创建集合，上传检测文档时选择该集合。系统使用每种文档的最新检测记录比对姓名、学号、单位和日期；缺少文档、字段有歧义或检测失败时，会提示人工复核。

| 方案 | 适用范围 | 依赖 |
| --- | --- | --- |
| `generic` | 五格式通用基础预检，按实际证据执行 | 项目基础依赖；OCR 可选 |
| `academic` | 论文与报告排版方案；复制后按学校要求设置正文、标题、分节参数 | 项目基础依赖；原生 DOCX 属性检测，无需外部引擎 |
| `certificate` | 实习证明页面、明确字段及人工签章复核 | 材料类型为 `certificate` |
| 学校依据生成的方案 | 已确认条款对应的材料类型和版本 | 方案声明的插件与能力 |
| `school-specific` | 已接入外部专项引擎后的 DOCX 检测；不出现在规则方案列表 | 学校专项引擎、来源资料及独立 Python 环境 |

自动提取的要求需对照学校文件核对；无法自动检查的条款仍需人工检查。姓名等字段一致不能证明签章或材料真实。

---

## 报告与边界

报告列出本次实际检查的项目、格式问题和待复核项，并保留检测时使用的文件与规则。修改稿会建立新的检测记录，历史报告不会被覆盖。

| 状态 | 含义 |
| --- | --- |
| 任务 `queued` / `running` | 等待执行 / 正在执行 |
| 任务 `completed` | 处理流程结束，可以仍有格式错误 |
| 任务 `failed` / `interrupted` | 执行失败 / 服务中断 |
| 结果 `needs_changes` | 检测到文档格式偏差 |
| 结果 `review_required` | 存在人工复核或未覆盖事项 |
| 结果 `passed` | 已覆盖的检查未发现问题，不等于学校全量验收通过 |
| 结果 `incomplete` | 执行或输入完整性不足，不能形成完整结论 |

逐规则状态为 `passed`、`failed`、`manual`、`not_checked`、`unsupported`、`error`、`not_applicable`。空问题列表、仅输入结构有效、人工项或排除项不能替代实际格式检查。报告分别展示文档偏差 `document_counts` 与执行异常 `execution_errors`。

可下载 HTML、Markdown、JSON 报告。HTML 报告可独立打开、搜索和筛选，无需联网；Markdown 适合阅读，JSON 供程序处理。检测过程的详细记录可在附件中查看，附件类型取决于所选插件。

**输入限制：** 单份原稿或学校来源最大 40MiB，提取正文最大 1MiB；JSON 原始文件另限 2MiB，解码全文也限 1MiB。PDF 最多处理 300 页、最多 OCR 20 页，部分读取失败或达到限制时保留不完整/待复核状态。

仅 DOCX 可另附 PDF 或使用可选的本机 Word/WPS 导出。文字一致不认证图表、分页和版本已配对。OCR 结果需核对数值、否定词及栏目；工具不认证签章、研究事实、查重率、AIGC 比例或学校最终接收结果。

---

## CLI

环境已激活时可使用 `python`；未激活时换成上文的 `.venv` 解释器路径。

```powershell
python -m formatly check --input '论文.docx' --profile generic --kind thesis --output '检测结果'
python -m formatly check --input '论文.pdf' --profile generic --json
python -m formatly check --input examples/document.json --profile generic
python -m formatly profiles list
python -m formatly profiles preflight generic --kind thesis --format pdf
python -m formatly doctor
python -m formatly jobs list --query '论文' --status completed --limit 50 --offset 0
python -m formatly repairs preview '任务ID'
python -m formatly repairs apply '任务ID' --plan-id '预览返回的计划ID' --select '选项ID' --output '修复结果'
```

退出码：`0` 为执行完成且无已识别格式错误，仍可能有人工项；`1` 为执行完成且发现格式错误；`2` 为输入、配置或执行不完整。自动化调用应同时检查报告。`--output` 需指向新的或空的目录，任务历史仍保存在数据目录。

<details>
<summary>学校依据、材料集合与专项命令</summary>

将以下占位 ID 替换为对应命令返回的实际 ID；路径按材料位置修改。

```powershell
python -m formatly schools create --name '本校毕业材料'
python -m formatly schools add-source '学校依据包ID' --source '论文模板.docx' --kind thesis --role template
python -m formatly schools add-source '学校依据包ID' --source '说明.pdf' --kind thesis --role instructions
python -m formatly schools show '学校依据包ID'
# 根据候选要求编辑审核文件，确认值、来源、模式与排除理由
python -m formatly schools confirm '学校依据包ID' --requirements '已审核要求.json' --expected-version 3
python -m formatly collections create --name '毕业材料' --required-kind thesis --required-kind intern --required-kind certificate
python -m formatly check --input '证明.docx' --kind certificate --profile certificate --collection '材料集合ID'
python -m formatly collections show '材料集合ID'
python -m formatly jobs show '任务ID'
python -m formatly jobs retry '任务ID'
# 普通 DOCX 导出需要 Windows、本机 Word/WPS，以及 requirements.txt 中的 pywin32
python -m formatly check --input '论文.docx' --profile generic --kind thesis --render-word
# 外部专项方案继续使用该引擎的导出接口
python -m formatly check --input '论文.docx' --profile school-specific --kind thesis --render-word
```

PDF 来源可用 `schools add-source --transcription '已核对转录.txt'` 提供校正文本。`jobs list` 返回 `{items, total, stats, offset, limit}`：列表为摘要，完整证据通过 `jobs show` 读取。更多方案与插件用法见[可运行示例](examples/README.md)。

</details>

---

## 开发与验证

前端使用 Vue 3、Composition API、Vite 和 TypeScript。准备 Node.js 22+ 后，先生成工作台和报告模板，再运行依赖模板的 Python 检查：

```powershell
cd frontend
npm ci
npm test
npm run typecheck
npm run build
cd ..
python -m pip install -r requirements.txt
ruff check .
pyright
python -m unittest discover -s tests -q
python -m compileall -q formatly examples/example-plugin scripts app.py start_dev.py
python scripts/submission_check.py
```

后端 Python 环境按快速开始准备并激活。前端构建写入 `frontend/dist`，包含工作台、报告模板和许可证；生产运行使用这些资源，不启动 Node.js。

`requirements.txt` 同时安装运行库、Ruff、Pyright、ReportLab、python-docx、Docling Parse 和 psutil。`pywin32` 带有 `sys_platform == "win32"` 标记，macOS 和 Linux 安装时会跳过。`ruff check .` 检查 Python 语法、未定义及未使用的名称、循环闭包绑定和选定的常见错误；`pyright` 按项目配置检查后端、脚本、测试、插件示例和根目录启动入口，使用 Python 3.11 类型规则与项目 `.venv`。构建目录、运行数据和缓存不参与源码检查。

先完成构建，再运行后端回归，避免重建期间报告模板缺失干扰检测。`python scripts/submission_check.py` 在提交前确认虚拟环境、构建结果、缓存、运行数据和本机 IDE 配置已被忽略，并在将进入提交的文本中查找私钥、令牌和失效文档链接。公开协议可从 `python -m formatly schemas` 或 `/api/schemas` 获取。Word/WPS 应用、Tesseract 与语言包仍由本机提供，不会随依赖清单安装。

```powershell
python start_dev.py                            # 后端 + Vite，默认局域网可访问
python start_dev.py --local-only --no-browser  # 仅本机，不打开浏览器
python start_dev.py stop                       # 在另一个终端停止本项目开发服务
```

开发前端默认 `5173`，后端默认 `8765`；`--backend-port`、`--frontend-port`、`--data-dir` 可调整配置，`--verbose-logs` 显示完整日志。启动器优先项目 `.venv`，探测后端、首页和 API 代理后打开浏览器；Ctrl+C 或 `stop` 只回收其创建的进程。端口冲突会明确报错。

单独运行 `npm run dev` 时，`FORMATLY_DEV_HOST`、`FORMATLY_DEV_PORT` 控制绑定，`FORMATLY_API_TARGET` 指定后端，默认 `http://127.0.0.1:8765`。界面、状态和 API 契约见[前端说明](frontend/README.md)与[前端架构](frontend/ARCHITECTURE.md)。工作台从项目目录启动，前端资源读取 `frontend/dist`。

---

## 目录结构

```text
app.py                        已构建工作台入口
start_dev.py                  Python + Vite 开发入口
启动工作台.cmd                Windows 启动器
启动工作台.sh                 macOS / Linux 启动器
formatly/                     Python 后端
  application/                共享业务服务、流水线、报告与修复
  documents/                  五格式文档读取与隔离 PDF worker
  persistence/                规则方案、学校依据、任务与材料集合
  interfaces/                 HTTP、命令行、启动和网络适配
  plugins/ / adapters/        检测插件与学校专项适配器
frontend/
  src/                        Vue 页面、组件、状态、API 和样式
  public/                     透明品牌图标与依赖许可
  scripts/                    独立报告壳与构建脚本
  tests/                      前端状态测试
  dist/                       构建结果，由 .gitignore 排除
scripts/                      评测、样本、校验和提交前检查
examples/                     文档、方案及插件示例
tests/                        Python 测试
docs/                         格式、结构、排版、导出与外部引擎说明
LICENSE                       MIT 许可证
```

---

## 文档

| 文档 | 内容 |
| --- | --- |
| [English](README_en.md) | 英文使用说明；当前工作台界面为中文 |
| [前端架构](frontend/ARCHITECTURE.md) | 组件、状态与交互 |
| [外部引擎接入](docs/external-engines.md) | 完整引擎目录、本机配置、分阶段检查、使用与撤销 |
| [格式与提取规范](docs/document-formats.md) | DOCX、PDF、文本、JSON 与 OCR 证据 |
| [论文与报告排版](docs/native-plugin.md) / [结构检测](docs/academic-structure.md) | 段落、标题、题注、参考文献和页码域的配置边界 |
| [本机导出](docs/office-rendering.md) | Windows 上的 Word/WPS 只读导出 |
| [可运行示例](examples/README.md) | JSON 原稿、规则方案和插件扩展 |

---

## 常见问题

**提示缺少前端资源怎么办？** 完成 `frontend` 中的 `npm ci` 与 `npm run build`，确认 `frontend/dist/index.html` 和 `report-template.html` 存在。已有完整资源时正常启动无需重复构建。

**扫描 PDF 没有识别到中文？** 运行 `python -m formatly doctor` 或打开“环境诊断”，检查 Tesseract 与语言包。默认优先 `chi_sim`，没有时使用 `eng`；可用 `FORMATLY_TESSERACT` 指定程序，用 `FORMATLY_OCR_LANGS=chi_sim+eng` 指定已安装语言。程序和模型不会自动下载，OCR 内容仍需核对。

**零错误为什么还显示待复核？** 人工项、不支持项、未执行要求和提取不完整会影响结论。任务完成、退出码为 0 或问题为空，都不能代替规则覆盖和学校人工验收。

**学校专项不可用？** 在“设置 → 运行环境 → 外部专项引擎”查看接入步骤和逐项检查。先在运行 Formatly 的主机准备完整兼容引擎，再运行 `python -m formatly engines configure --root '引擎根目录'`；验证通过后保存配置，重启服务即可预检并使用。独立 Python 可用 `--python` 指定，`engines check` 复查，`engines clear` 撤销，详见[接入指南](docs/external-engines.md)。环境变量优先于本机保存配置。日常检测用预置方案，或在“学校要求”上传模板和说明、核对确认后保存方案；这些流程不依赖外部引擎。

**数据保存在哪？** 可用 `--data-dir` 或 `FORMATLY_DATA_DIR` 指定。默认 Windows 为 `%LOCALAPPDATA%\Formatly`，macOS 为 `~/Library/Application Support/Formatly`，Linux 为 `$XDG_DATA_HOME/formatly` 或 `~/.local/share/formatly`。备份完整数据目录可保留规则、来源、任务和报告。测试临时文件写在 `.verification/tmp`，开发停止令牌写在 `.formatly/dev`，都不是用户数据。

**局域网其他设备打不开？** 使用日志中的运行机器 IPv4 地址，确认没有启用 `--local-only`，并检查网络隔离和主机防火墙。服务保留 Host 与同源校验；当前数据目录不提供多用户隔离，多用户部署需要相应的身份认证与访问控制。

**`.doc` 或 PDF 配对能直接检查吗？** `.doc` 请先另存为 DOCX；仅 DOCX 可另附 PDF。PDF 原稿本身使用同一个检测入口，不接受另一份配对 PDF。

---

## 许可

Formatly 的代码、前端、示例和项目文档采用 [MIT License](LICENSE)，版权为 `Copyright (c) 2026 Formatly`。

第三方依赖遵循各自的许可证。[前端依赖许可说明](frontend/public/THIRD_PARTY_NOTICES.txt)保留 Vue 与 Vite 运行资源的版权和许可全文，随前端、发布包及独立 HTML 报告提供；Python 依赖保留各自安装包内的声明。
