# Formatly 前端架构与验收契约

Formatly 前端使用 Vue 3 + Vite + TypeScript、Composition API 和可复用组件；源码位于 `frontend/src`，生产构建输出到 `frontend/dist`。品牌名称为 **Formatly**，副标题为 **Academic formatting, checked.**。本文定义前端的模块职责、交互行为、接口契约及验收要求。

## 1. 源码与运行边界

- `src/App.vue`：页面编排、hash 路由、应用级状态实例的创建与释放。
- `src/api.ts`：唯一 HTTP 请求入口，封装 JSON、multipart、超时和可读 `ApiError`。
- `src/composables/useAuditStore.ts`：方案、插件、最近任务、完整任务详情、附件、诊断、保存状态与轮询。
- `src/composables/useJobHistory.ts`：历史搜索、状态筛选、服务端分页、后续读取、漂移检测和历史页刷新。
- `src/composables/useAuditSetup.ts`：按方案、文档类型和输入格式预检、材料集合选项和提交准备状态。
- `src/composables/useSingleAuditActions.ts`：单次提交与重试的路由、草稿版本和迟到响应保护。
- `src/composables/useReportIssues.ts`、`useCompleteReportPrint.ts`：完整结果索引、每页 10 条紧凑问题、完整搜索和同步的全量 Vue 打印副本。
- `src/composables/usePagedItems.ts`、`src/components/ListPagination.vue`：规则检查、学校要求、修复候选、复检对照、材料与已读取历史的有界分页；保留底层全量数据。
- `src/composables/useAuditFiles.ts`：原稿与可选 PDF 校验；替换或移除主稿同步清空旧配对，非 DOCX 限制配对与渲染。
- `src/composables/useDocumentCapabilities.ts`：PDF/OCR 能力读取、刷新与迟到响应守卫。
- `src/composables/useSchoolWorkspace.ts`：学校依据列表、来源上传、候选确认/排除及生成方案的异步状态。
- `src/composables/useSchoolSourceText.ts`：PDF 校正文本按 UTF-8 字节限制为 1 MiB，换文件清空校正文，超限禁止提交并显示原因。
- `src/composables/useRequirementEditor.ts`：候选草稿、类型化值、冲突与非法输入提示、确认准备状态；页面只编辑后端规则协议。
- `src/composables/useCollectionWorkspace.ts`：材料集合列表、详情、建立集合与刷新状态。
- `src/components`：`AppShell`、`Sidebar`、`Topbar`、`UploadDropzone`、`StatCard`、`StatusBadge`、`IssueCard`、`RuleCheckList`、`ReportContent`、`ArtifactList`、`ProfileDialog`，以及共享能力与提取说明 `DocumentCapabilities`、`DocumentExtraction`。
- `src/views`：工作台页面及独立报告 `StandaloneReport.vue`；`ResultView.vue` 与独立报告共用 `ReportContent.vue`。
- `src/utils/report.ts`：共享报告证据、位置、规则与检测组件的中文显示；技术标识保留在详情中。
- `src/utils/documents.ts`：五种格式扩展名、上传大小与可读错误的共享校验。
- `src/standalone-report.ts`：独立报告 Vue 入口，读取内嵌结果数据。
- `scripts/report.html`、`scripts/build-report.mjs`：报告壳和构建脚本，生成可安全注入数据的单文件模板。
- `src/styles`：主题 token、组件状态和响应式布局。
- `src/components/AppIcon.vue`：本地 SVG 图标；图标默认对辅助技术隐藏，控件通过文字或标签提供名称。
- `src/components/ThemeToggle.vue` 与 `src/composables/useTheme.ts`：工作台和报告共享主题开关；Vue 插件提供应用内统一状态并在卸载时释放监听。

浅色、深色配色集中于 `src/styles/tokens.css`，页面和组件使用语义变量。首次使用按系统主题显示，手动选择保存为浏览器本地 `formatly.theme`，跨标签同步；本地存储不可用时保留当前会话选择。工作台在加载前通过同源 `public/assets/theme-init.js` 设置主题，脚本随 `/assets/` 一同分发。报告使用已计算 CSP 哈希的内嵌渲染器初始化主题，不加载外部脚本。暗色变量只应用于屏幕，打印恢复浅色并隐藏主题开关，原稿图像和 PDF 不做主题滤镜。

组件负责展示和事件，API 调用集中于 `api.ts`，状态与异步处理集中于 composables。学校规则由 profile 和插件提供，Web 与 CLI 共用 Python `AuditService` 和检测流水线；页面按 Vue 组件渲染，不承担检测规则执行。

界面采用浅色导航、单一蓝色操作强调、12px 面板与 8px 表单圆角，中文正文 16px、表单 15px。工作台主区和独立报告随可用宽度展开，不设置整页最大宽度；主区与顶栏使用相同边距，桌面为 24–40px、手机为 12–16px。新建检测的工作区在 880px 以下改为单列，壳层在 768px 以下使用可收起菜单；学校要求、方案、报告、修复和设置列表保持每页 10 条。规则摘要和修复候选内部滚动，弹窗固定标题与操作区。报告数值单位由明确规则标识决定，不改变原始 JSON 证据。打印隐藏工作台导航，完整副本解除证据区裁剪。

筛选标签使用独立文本节点容器，选择框按剩余宽度伸缩，不套用整行表单的宽度。常规操作按钮和状态短语保持完整，空间不足时由外层操作组换行；文件名、说明及证据继续自然折行。历史记录的状态网格使用完整列宽；报告分页的页码与总页数保持同组，窄屏品牌副标题独占一行。移除上传文件后，焦点返回上传区；顶部操作最小高度统一为 44px。

`useReportWorkspace` 在切换问题时清空旧复核版本；成功读取对应记录后才允许保存，读失败不会提交空草稿，解决 CAS 冲突时保留用户输入。材料列表与规则检查通过集合身份区分轮询和切换：同集合更新保留页码并在数量减少时校正，切集合或筛选复位；完整报告切换仍遵守报告自身身份。

`frontend/dist` 只存放前端构建产物。`npm run build` 先由 Vite 清空该目录并构建工作台，再运行 `scripts/build-report.mjs` 生成 `report-template.html`。透明品牌图标源文件为 `frontend/public/assets/formatly-mark.png`，工作台复制为本地资源，报告模板则内嵌为 data URI；报告的 Vue IIFE 和 CSS 也全部内嵌。页面、报告组件、报告壳和构建脚本均在 `frontend/` 维护，Python `formatly/application/reports.py` 仅安全注入 JSON 及导出 Markdown，不维护 HTML 布局或样式。发布后的 Python 服务使用这些资源，运行不需要 Node.js、联网或 CDN。

开发服务器默认绑定 `0.0.0.0:5173`，端口占用时退出，不自动换端口。环境变量 `FORMATLY_DEV_HOST`、`FORMATLY_DEV_PORT` 可修改绑定；`FORMATLY_API_TARGET` 默认为 `http://127.0.0.1:8765`。开发中间件按最终绑定、本机 IPv4 接口及实际监听端口验证 Host，API 请求的 Origin 若存在须与入站 Host 的 HTTP Origin 一致，再向后端改写 Origin；外站来源明确拒绝，不使用通配 Host/CORS。

根目录 `python start_dev.py` 一键启动同一 Python 后端及 Vite，检查环境、探测后端 `/api/health` 和前端首页就绪后自动打开浏览器，默认支持局域网访问。`--local-only` 限定本机，`--no-browser` 关闭自动打开，`--backend-port`、`--frontend-port` 可修改端口；启动器自动同步 Vite 的代理目标。Ctrl+C 回收本次创建的子进程，端口占用报错，不停止无关程序。日常使用已构建资源时运行 `python app.py` 即可，默认 `0.0.0.0:8765`、就绪后打开浏览器，支持 `--local-only`、`--no-browser`、`--host`、`--port`，不要求安装或运行 Node.js。两种入口共享后端检测链路，区别仅为静态发布页面或 Vite 热更新。

## 2. 页面与路由

路由来源为 `window.location.hash`，浏览器前进、后退和刷新后均应恢复当前页面。未知 hash 回退到新建检测。

| 路由 | 页面 | 主要行为 |
| --- | --- | --- |
| `#new` | `NewAuditView` | 选择/拖放 DOCX/PDF/TXT/MD/JSON，DOCX 可另附 PDF；选择方案、三种文档类型与可选集合，通过格式预检后提交，展示能力、全库统计与最近任务 |
| `#history` | `HistoryView` | 按文件名搜索全部历史、状态筛选，已读取记录每页 10 条，继续读取后续记录并打开任务 |
| `#job/<id>` | `ResultView` | 读取完整详情、轮询忙碌任务；四分区查看紧凑问题、规则检查、文档信息和修复/报告，原快照重试或上传修改稿及下载附件 |
| `#profiles` | `ProfilesView` / `ProfileDialog` | 查看方案、复制为自定义方案、校验和保存 |
| `#plugins` | `PluginsView` | 展示插件能力与不可用原因 |
| `#doctor` | `DoctorView` | 环境诊断、重新检查、显示无效方案和缺失依赖 |
| `#schools` / `#schools/<id>` | `SchoolsView` | 创建学校依据包，上传分类型模板/说明，核对来源、候选、冲突、确认与排除，生成独立版本方案 |
| `#collections` / `#collections/<id>` | `CollectionsView` | 创建材料集合、选择必需类型、添加检测材料，查看各类型最新版本的字段一致性及证据 |

侧栏按用户任务提供四个入口：新建检测、学校要求、检测记录、设置。学校要求内用分类导航切换模板/说明与已保存方案；检测记录内切换全部记录与材料分组核验；设置内切换运行环境与检测能力。原有八种功能页面及其 hash 路由仍可直接访问，子页高亮其所属侧栏入口，学校和集合详情 ID 同样保存在 hash 中。

新建检测页先展示学校要求和原稿检测两个流程入口。`#schools/new` 直接展示学校名称、材料类型、来源角色及文件上传；首次上传依次建立学校要求和保存来源，失败后保留已建立的要求与文件，重试不重复建立。学校页第 3 步仅展示当前已确认版本关联的方案，新增来源使学校状态变为 draft 后不再将旧方案展示为当前方案。确认响应中的方案立即合入应用状态，较早的方案列表响应不能覆盖它们。

学校页及已保存方案均可直接使用方案检测，进入 `#new?profile=<id>&kind=<type>`；可选 `collection` 记录材料集合。刷新通过 hash 恢复这些选择，原稿仍须用户重新选择。未填写 kind 时为 thesis，非法类型回退为 thesis。界面不会根据模板内容自动承诺所有要求均可检查，确认、人工复核、排除和能力预检继续生效。

工作台和独立 HTML 复用同一 `ReportContent.vue` 四分区：问题明细、规则检查、文档信息、修复与报告（独立报告为方案与记录）。默认只显示每页 10 条紧凑问题，按需展开一项的格式比对、出处和证据，搜索覆盖全量数据且保留原始问题索引。已知状态和属性中文显示，原始技术标识、哈希及完整记录按需展开。工作台的修复、复检和附件通过插槽放入第四区，不在主问题列表之后全部平铺。

独立 HTML 不使用工作台路由或 API。单个文件内含结果及运行资源，核心内容与交互不依赖相邻文件或网络；不提供相对 JSON、Markdown 或方案链接，完整附件继续从工作台下载。API 将 HTML 产物强制作为附件下载，工作台 CSP 保持原策略，已有历史报告不重写。打印使用完整共享组件副本，包含全量问题、规则和文档信息，结束后释放；不把分页后的当前十项当作完整打印内容。

创建任务成功只表示已入队。发起页面和草稿未变化时跳转到 `#job/<id>`；否则保留当前页面与新草稿，显示后台任务入口。失败或中断任务仍可查看错误与附件。“重试本次检测”建立新任务，使用原输入、原规则和原集合关联；“检测修改稿”打开新建页并带入方案、类型和集合，用户必须重新选择实际文件。修改后的规则只影响新任务，不能改写历史快照。

`RepairPanel.vue` 和 `useDocumentRepair.ts` 提供 DOCX 按问题修复。`GET /api/jobs/<id>/repairs` 读取计划、候选及不可处理原因；`POST` 同路径只传 `{plan_id, selected_ids}`，后端生成副本后返回新 `Job`，由应用导航到新 hash 并沿用任务轮询。预览默认不选，逐项展示中文位置、要求和实际值，候选与手动处理项分别每页 10 条；翻页保留跨页选择，提交仍使用全部已选 ID。未选择、读取中、提交中及已创建时禁用提交。切换任务、输入/规则哈希改变或卸载使旧响应失效。修复来源摘要在工作台与独立报告共享，原任务链接只出现在在线结果页，下载来自新任务 `repaired.docx` 与 `repair.json`。

```text
queued -> running -> completed
             |         +-> result.status: passed / needs_changes / review_required
             +-> failed（含检测结果 incomplete）
running -> interrupted（服务重启时确认原执行进程已退出）
completed/failed/interrupted -> retry -> 新的 queued 任务
```

## 3. 状态、轮询与请求守卫

`useAuditStore()` 每次调用建立独立实例，不在模块顶层保存共享状态或计时器。卸载时释放本实例的轮询并使未完成请求失效，不能影响其他实例。

任务列表只保存摘要，详情状态 `selectedJob` 只接收 `/api/jobs/<id>` 返回的完整任务。打开结果页显示详情加载状态；不能先用摘要渲染“没有问题”，也不能在列表刷新时覆盖已加载的问题和引擎证据。切换任务使用当前任务 ID 与请求序号守卫，迟到响应不覆盖新选择。列表读取使用请求序号和本地变更版本，避免过期响应移除刚创建的任务；方案刷新同样保留请求期间刚保存的方案。

仅在最近任务或当前详情存在 `queued/running` 时调度应用轮询，单实例无重叠 poll。列表与详情独立处理失败，列表请求失败不能阻止当前报告完成。到达终态后加载附件，按任务 ID 去重在途附件请求。API 错误必须保留为可见提示，不能清空已读取的报告。

`useJobHistory()` 独立维护搜索、状态、读取偏移、总数、加载和错误。搜索/筛选防抖 250ms 后从第一页重新读取，过期请求失效；服务端每次读取 50 条，追加按 ID 去重并检查首页、总量和重复边界的漂移。`HistoryView` 对已读取结果每页显示 10 条；“读取后续记录”读取下一批后定位新增记录，不将全部缓存平铺。可见历史页含忙碌任务时继续刷新，卸载清除轮询与防抖计时器。

新建页和侧栏计数使用后端 `stats`，不能用当前页条数或本地筛选结果推断累计任务。保存、提交和重试均有在途禁用状态；页面、表单和对话框错误按操作展示。

`useAuditSetup()` 监听方案、类型与原稿实际格式，变更后同步使此前的预检失效，未选文件默认 docx；未取得当前组合的可用结果或仍在预检时不能提交。格式/类型不匹配、插件不可用和配置无消费者必须展示原因。`useAuditFiles()` 同步监听主稿引用，替换或移除时清空配对 PDF 与其错误，即使新主稿仍为 DOCX 也不沿用旧配对；提交时再次限制配对与渲染。能力、学校与集合 composables 使用请求版本和卸载守卫，不能将迟到详情写入新选择；保存期间禁用重复提交。

学校流程为“创建依据包 → 按类型与角色上传来源 → 核对候选及出处 → 确认、解决冲突或填写理由排除 → 生成各类型方案 → 新建检测”。五种格式均自动提取有限明确属性或短语；PDF 优先原生文字，扫描/混合页在本机 OCR 可用时识别，展示逐页来源、完整性及警告。PDF 人工转录为可选校正覆盖，原始提取仍保留；更换来源文件时清空此前的覆盖文本。候选不是自动生效校规，未确认、OCR 不确定或人工条款保留复核。排除须有理由并保留来源，不能掩盖已执行冲突。姓名、学号、单位、起止日期仅从明确标签字段提取，字段一致不认证签章或材料真实性。

学校正文候选以 `scope_style_ids` 显示可编辑的适用样式，模板候选保留实际样式；后端按属性保存范围，未确认范围时不以默认样式替代。`useRequirementEditor()` 按目标转换数值与样式数组后比较冲突，`25`/`25.0` 和去重排序后的同一组样式不产生伪冲突，非法数字或数组单独提示；确认后的有效要求仍由后端校验。新增草稿标识不依赖安全上下文专有的 `crypto.randomUUID()`，普通局域网 HTTP 也可新增要求。

集合流程为“创建集合并指定必需类型 → 逐件检测时关联集合 → 刷新核验”。每种必需类型只用最新任务，保留较早版本 ID；最新任务失败、忙碌或不完整时不能使用较早的成功任务替代当前结果。字段缺失、歧义或不足两份有效证据必须提示复核。

## 4. API 契约

所有请求从 `api.ts` 发起，使用 `credentials: 'same-origin'` 与 `Accept: application/json`；JSON 写请求设置 `Content-Type: application/json`。普通读取超时 30 秒，任务上传、能力探测、预检和诊断 60 秒，需同步解析/OCR 的学校来源上传为 240 秒。网络错误、超时、HTTP 失败和非 JSON 响应统一转为 `ApiError {message, status}`。

| 方法 | 路径 | 请求 | 成功响应 |
| --- | --- | --- | --- |
| `GET` | `/api/health` | 无 | `{status: 'ok', version}` |
| `GET` | `/api/capabilities` | 无 | `{formats, pdf: {available, reason}, ocr: {available, reason, languages, ...}, limits}` |
| `GET` | `/api/profiles` | 无 | `{items: Profile[], warnings: ProfileWarning[]}` |
| `GET` | `/api/profiles/<id>` | 无 | 完整方案 |
| `GET` | `/api/profiles/<id>/preflight` | 查询参数 `kind`、`format`（默认 docx） | `{available, plugins, warnings, kind_compatible, input_format}` |
| `POST` | `/api/profiles` | JSON 方案 | 保存后的方案，HTTP 201 |
| `GET` | `/api/plugins` | 无 | `{items: Plugin[]}` |
| `GET` | `/api/doctor` | 无 | `{status, checks}` |
| `GET` | `/api/jobs` | `q`、`status`、`limit`、`offset` | `{items, total, stats, offset, limit}` |
| `GET` | `/api/jobs/<id>` | 无 | 完整任务与结果 |
| `POST` | `/api/jobs` | multipart 文档与选项 | 新任务，HTTP 202 |
| `POST` | `/api/jobs/<id>/retry` | `{}` | 新任务，HTTP 202 |
| `GET` | `/api/jobs/<id>/artifacts` | 无 | `{items: Artifact[]}` |
| `GET` | `/api/jobs/<id>/artifacts/<path>` | 无 | 限定在本任务目录内的文件流 |
| `GET` | `/api/schools` | 无 | `{items: School[], warnings: WorkspaceWarning[]}` |
| `POST` | `/api/schools` | JSON `{name}` | 学校依据包，HTTP 201 |
| `GET` | `/api/schools/<id>` | 无 | 学校来源、候选/要求、版本、冲突与方案 |
| `POST` | `/api/schools/<id>/sources` | multipart `source/kind/role/transcription` | 更新后的依据包，HTTP 201 |
| `GET` | `/api/schools/<id>/sources/<source-id>` | 无 | 经哈希核验的来源原件附件 |
| `POST` | `/api/schools/<id>/confirm` | JSON `{requirements, expected_version}` | `{school, profiles}` |
| `GET` | `/api/collections` | 无 | `{items: MaterialCollection[], warnings: WorkspaceWarning[]}` |
| `POST` | `/api/collections` | JSON `{name, required_kinds}` | 材料集合，HTTP 201 |
| `GET` | `/api/collections/<id>` | 无 | 集合、关联任务、最新版本选择、checks 与汇总 |

历史参数约束：`q` 按文件名做不区分大小写的子串匹配，最多 200 字符；`status` 为空或合法任务状态；`limit` 默认为 100，范围 1–100；`offset` 默认为 0，必须非负。响应 `total` 是筛选后的记录总数，`stats` 则是全部历史统计。摘要的 `result` 含 `status/counts/document_counts/execution_errors`，详情才包含完整 `issues`、`engines`、`coverage` 和快照，不可互换。

```ts
interface JobStats {
  total: number
  completed: number
  needs_changes: number // document_counts.error > 0 的任务数，缺少 document_counts 时使用 counts.error
}
interface JobPage {
  items: JobSummary[]
  total: number
  stats: JobStats
  offset: number
  limit: number
}
interface ProfileWarning {
  id: string
  file: string
  message: string
}
```

CLI 对应命令为 `formatly jobs list --query '论文' --status completed --limit 50 --offset 0`，复用同一分页服务和响应结构；`jobs show <id>` 读取详情。当前 TypeScript 类型定义以 `src/types.ts` 为准，以上 `JobSummary` 表示接口摘要语义。

任务上传字段为必需的 `document`（DOCX/PDF/TXT/MD/JSON），可选的 `pdf`，以及 `profile_id`、`kind`、`render_word`、可选 `collection_id`。单文件必须非空且不超过 40MiB，PDF 需有有效签名；`kind` 为 `thesis/intern/certificate`。只有 DOCX 可另附 PDF，且仅包含 `legacy-school` 的方案可启用 Word/WPS 只读渲染，学校专项引擎仅支持 DOCX 及前两种类型。通用方案会解析所附 PDF 页面并核对可提取文字；即使一致也不认证版本、分页或图表配对。

学校来源字段 `source` 支持相同五种格式，单文件上限 40MiB；`role` 为 `template/instructions`，`kind` 为上述三种类型，`transcription` 是 PDF 可选的已核对覆盖文本。原件、有效文本、自动提取及元数据分别记录哈希，有覆盖时额外记录 `transcription_sha256`，确认和下载均核验；来源显示 `text_method` 与 `extraction`。提取文本上限 1MiB，JSON 文件另限 2MiB。确认请求保留来源 ID、位置、摘录及 `mode/confirmed/excluded/exclusion_reason`；已排除项须确认且理由非空，原始候选不因漏传删除。JSON 写请求上限 2MiB，学校方案最多 1500 条要求且上限 2MiB；普通方案上限 128KiB，超限明确拒绝。

方案必须以 `docx-package` 作为第一项插件，内置方案只读。自定义 JSON 损坏、ID 与文件名不一致、内容无效或覆盖内置 ID 时，有效方案照常返回，`warnings` 指出文件与原因，页面和诊断均可见；原文件保留，修复后刷新重新读取。

方案可带 `kinds`、`school`、`requirements`，学校确认生成各类型独立版本；证明内置方案为 `certificate`。插件通过 `settings_keys` 声明消费的顶层配置，未知或无消费者的内置配置不能静默接受；外部插件未声明配置消费者时保留复核警告，未声明 `formats` 时只接受 DOCX。页面展示支持格式和不可用原因，只编辑后端协议，不解释执行规则。

结果的 `coverage` 含 `checks/summary/format_checks/complete/scope`。检查状态固定为 `passed/failed/manual/not_checked/unsupported/error/not_applicable` 七种；已确认排除记为 `not_applicable`，保留理由但不计自动通过。仅包结构有效、空规则或没有实际格式证据均不能表现为格式通过。学校要求只有匹配实际目标、预期值和已确认正文范围的执行证据才能计已覆盖。流水线通过 `check_id`、问题的 `check_ids` 和学校汇总的 `observed_check_ids` 关联具体执行项，前端不按同名规则推测出处；`IssueCard`、`RuleCheckList` 与共享格式化函数同时支持单个来源和来源数组，逐项展示真实文件、位置和摘录。

共享报告展示 `input_format/document_extraction`、`profile_snapshot/profile_sha256`、条款出处、引擎 `evidence`、正文检查范围及输入完整性；提取摘要包含方法、页数、完整性、需复核标志与警告。`document_counts` 表示原稿问题，数字 `execution_errors` 表示引擎或完整性异常；`counts` 记录全部问题计数。五种原稿按实际后缀保存快照并核验哈希，CLI 另核对原文件。哈希不认证真实性或 PDF 配对。历史结果缺少字段时显示已有计数并提示未记录覆盖，不能补造证据。

DOCX 检查其真实样式与属性；PDF 可检查实际页面尺寸、原生文字和字体清单，只有 `body.pdf_region_mm` 明确上/下/左/右正文区域后才比较该区域原生文字的字体/字号，OCR 字体始终待复核，不推断页边距、Word 样式或行距。TXT/MD/JSON 仅检查文本结构和字段，不提供排版证据。普通 JSON 保留字段路径，结构化 `formatly.document.v1` 接受标题/段落/字段；JSON 原稿不作为 profile 导入。

PDF 依赖随 `requirements.txt` 安装的 `pdfplumber`。扫描及混合页使用可选本机 Tesseract，默认 PATH 发现，也支持 `FORMATLY_TESSERACT` 和 `FORMATLY_OCR_LANGS`（如已安装的 `chi_sim+eng`）。`DocumentCapabilities` 显示可用性和中文语言名称，明确称为可用语言而不推测本次所选语言；未知代码与方向识别数据放入详情。缺失时明确提示，不自动下载或调用云 OCR；识别及学校候选必须人工核对。

## 5. 可读性与交互

| 内容 | 基线 |
| --- | --- |
| 正文 | 16px，中文行高约 1.7–1.8 |
| 表单、按钮 | 15px，主要控件最小高度 44px |
| 桌面页面标题 | 32–40px |
| 移动端页面标题 | 26px |
| 分区标题 | 22px，移动端 20px |
| 辅助说明 | 14px；仅次要 metadata 可使用 12px |

视口宽度控制导航与工作台壳层，内容按实际可用宽度调整：

| 视口宽度 | 布局约定 |
| --- | --- |
| ≥ 1600px | 大屏侧栏 272px，内容区最大宽度 1600px，保持居中与流式留白 |
| 1200–1599px | 常规桌面侧栏 248px，内容区按剩余空间伸展 |
| 768–1199px | 中屏侧栏 208px，缩小边距，内容区保持可读字号 |
| < 768px | 品牌置于页面顶部，菜单按钮控制双列折叠导航；表单与主要业务分栏纵向排列 |
| < 360px | 进一步收紧边距，结果操作与弹窗按钮改单列，保持 44px 最小触控高度 |

`.workspace` 与独立报告 `.standalone-report` 均提供名为 `workspace` 的 `inline-size` 容器。组件按该容器的可用宽度响应，避免将侧栏占用的空间误算为内容宽度。断点规则集中在 `src/styles/components.css`，修复预览和共享报告的局部规则保留在对应 Vue 组件中。

| `workspace` 容器宽度 | 内容布局 |
| --- | --- |
| ≤ 1080px | 新建检测、结果底部区域、规则/插件卡片与材料选择区域改单列；结果筛选与搜索纵向排列 |
| ≤ 800px | 要求表单与预期/实际格式对比改单列 |
| ≤ 640px | 统计卡片压缩间距；检测记录中文档名称与状态分行；工具栏及结果操作按可用宽度排列 |

独立报告复用相同的报告组件与容器布局，最大内容宽度同为 1600px。长文档名称、条款、证据与校验值可在容器内换行，不能通过裁切整个页面掩盖横向溢出。小屏弹窗保留视口边距与内部滚动，页面缩放后仍应能够访问全部字段和操作。

界面按工作台壳层、业务视图和共享组件组织，交互状态与键盘操作遵循一致约定。键盘焦点应清晰可见；小屏菜单通过按钮的 `aria-expanded` 和 `aria-controls` 表达开合状态，选择页面后收起，Escape 收起并恢复菜单按钮焦点。路由切换后聚焦主要内容，保留浏览器刷新、前进和后退行为。弹窗支持 Escape、焦点约束与关闭后的焦点恢复；加载和禁用态保持一致，错误通过页面内可读提示展示。

响应式验收宽度为 320、390、767、768、1024、1280、1440、1920px，覆盖最窄屏、手机、导航切换边界、中屏及大屏；补充检查 2560、3840px 超宽屏和 844×390px 横屏。各宽度检查品牌与菜单、表单、记录、结果、弹窗和独立报告是否存在重叠或横向溢出，同时检查触控高度、键盘菜单、Escape 与路由焦点。该尺寸矩阵定义布局验收范围，不能替代文档检测准确率或真实学校材料的业务验收。

全站以功能名称、操作和实际状态为主，侧栏、顶栏及页脚不重复展示运行口号或技术说明。方案与插件描述、文件校验和完整配置按需展开；具体错误、缺失依赖、未覆盖要求与待复核结论保持可见。

上传页的方案说明和 PDF 识别状态按需展开，识别异常时自动展开；仅在选择 DOCX 后提供附加 PDF，原稿为 PDF 或已附 PDF 时检查 PDF 能力，学校来源为 PDF 时才展示识别状态。

## 6. 验证与发布

前端开发和回归使用 Node.js 22 或更高版本。在 `frontend/` 执行 `npm ci`、`npm test`、`npm run typecheck`、`npm run build`。`npm ci` 按 `package-lock.json` 恢复依赖；清理环境时保留该锁文件和 `frontend/public` 中的品牌源图。`npm test` 使用 Node.js 内置测试运行器验证前端行为，真实浏览器验收独立执行。

修改前端或清除构建资源后，必须先生成完整报告模板，再在根目录运行依赖 HTML 导出的 Python 测试和编译检查：

```powershell
python -m unittest discover -s tests -q
python -m compileall -q formatly examples/example-plugin scripts
```

已有完整构建资源的源码检出可以直接运行 Python，正常启动无需重复构建。工作台从项目目录启动并读取 `frontend/dist`。历史报告和原始证据不作为缓存清理。生产运行不需要 Node.js。

浏览器验收至少覆盖：

- 本机 8765 首页、透明品牌图标、新建、历史、结果、方案复制弹窗、插件、诊断、学校依据和材料核验。
- 中文字号、桌面与移动端布局、无横向溢出、键盘焦点、弹窗关闭与禁用态。
- 全部历史的搜索筛选、已读取记录分页、读取后续记录和全库统计；从历史打开完整报告并在刷新后保留问题。
- 五种原稿与三类型预检、主稿替换/移除（含 DOCX→DOCX）后配对清空和迟到响应失效、非 DOCX 渲染禁用；从排队到终态轮询、原快照重试与修改稿、附件和接口失败提示。
- 学校五种来源上传、原生 PDF/中文扫描/混合页的提取与警告、OCR 缺失能力提示、可选转录覆盖及其哈希、来源下载、候选确认/人工/有理由排除、冲突与超限、版本方案及格式/类型禁用。
- 普通局域网 HTTP 新增要求、正文适用样式编辑、等值数值/样式数组不误报冲突，真实冲突及非法值仍阻止确认。
- 普通/结构化 JSON、非法 schema 与损坏输入；TXT/MD/JSON 不虚构排版检查，PDF 未明确正文区域不自动判定正文的字体/字号。
- 集合必需类型、最新版本选择、缺失/歧义字段、最新任务失败时保留该版本的失败状态、实际字段来源和不认证签章的边界提示。
- 七状态覆盖、学校出处、规则快照哈希、执行错误与文档偏差分开显示，以及历史结果缺少字段时的提示。
- hash 路由的直接打开、刷新、前进和后退。
- 工作台与独立 HTML 的报告内容、计数、证据格式化和筛选搜索一致；HTML 下载保持附件响应，其他附件入口完整。
- 在支持本地文件协议的浏览器中将 HTML 单独打开，核对核心内容和筛选搜索不依赖相邻文件或网络，并检查特殊文本安全展示及 CSP。

源码目录边界：`formatly/` 只含 Python 后端，`frontend/` 集中维护 Vue 源码、图标、构建脚本和 `dist/`。运行时直接读取 `frontend/dist/`，HTTP 和报告使用同一个资源定位入口。


学校确认 API 必须携带读取草稿时的正整数 `expected_version`，缺失或非法返回 400；服务端在写锁内比较当前版本，过期返回 409，不保存旧值。学校编辑器对未修改条款接收服务器更新；冲突修改保留在本地，用户明确选择采用最新要求或核对后保留本地修改，并重新确认后方可提交。未保存的空白新增项不提交，已保存条款通过保留待确认或有理由排除处理，不能按新增项移除。

复制方案保留全部已选插件；运行环境不可用只提示条件，不自动移除插件。学校方案副本若修改规则参数或插件集合，将转为独立自定义方案，移除学校确认身份和条款快照；参数仅调整 JSON 键顺序不会改变身份。

未修改执行参数的复制/导入同时保留 `requirements/scoped_rules`，学校副本通过 `school.source_profile_id` 指向原发布方案；复制副本不改变该来源。普通多范围方案不能在简化表单中静默丢失执行规则，需编辑完整 JSON 后导入。批量逐稿复用 `useDocumentScope/DocumentScopePicker`，稳定文件槽位保留切换状态，按顺序提交范围绑定；普通方案启动匹配后，未完成或过期不能提交，明确退出才恢复直接检测。

## 规则与报告工作流

- `RuleFields` 消费后端字段元数据，`ProfileSummary` 展示预计能力；未知插件参数和高级 JSON 保留。`useProfileTrial` 将匿名样例送入普通任务服务。
- `useSchoolDraftPersistence` 负责服务端草稿读取、自动保存、恢复、丢弃、CAS 冲突及离开提示；`useRequirementEditor` 维护三方合并、类型化编辑和确认规则。条款每页 10 条，筛选切换同步回首页，新增条目进入其所在页；筛选与分页保留全量草稿原始索引，保存和确认仍提交全部要求。
- `useReportWorkspace` 管理证据、复检对照及人工意见的加载、版本冲突和迟到响应；`ReportWorkspace` 提供原稿页框/片段与条款、格式比对和独立意见。复检对照按已解决、仍存在、新增、无法比较切换，各组每页 10 条。独立报告只使用 ReportContent 数据展示，不加入在线复核 API。
- `CollectionsView` 对集合中的材料记录每页显示 10 条，旧版本标记与最新任务核验逻辑保持原样，核验结果使用共享规则列表分页；翻页不改变参与核验的任务。
- `useBatchAudit` 负责多文件检查、实际格式预检、提交幂等键、逐项结果、轮询去重和视图代次隔离。预检失败可用“重新核对方案”重试，保留输入和仍有效的范围；重复点击复用正在进行的预检。发送时固定请求和幂等键，预览自动到期不丢弃有效回执，传输失败可“重试原批次”。主动换稿、换方案、范围编辑、切页和卸载使旧意图失效。`#batch/<id>` 刷新后读取已保存批次，未提交 File 刷新后重新选择。
- `JobProgress` 显示后端真实阶段与取消请求；运行中“检测修改稿”禁用。`#new?...&revision=<id>` 刷新保留父修订关系，提交前仍重新选择原稿。

上述请求统一封装于 `src/api.ts`；页面不包含 Python 规则逻辑。方案、报告和草稿的技术详情按需展开。

学校字体要求的比较规则来自后端字段元数据，前端不另存字体别名字典；等价字体保留各自来源和原值。页面/分节要求移除全部分节选择即为全文，清除旧绑定状态并保留来源历史；正文和页码空范围继续显示待匹配。
