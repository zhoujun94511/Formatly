# Formatly Vue 前端

工作台和报告通过 `ThemeToggle.vue` 切换浅色、深色模式。`useTheme.ts` 的 Vue 插件统一提供状态，首次跟随系统，手动偏好存于本地浏览器并同步到同源标签页；卸载时移除监听。`tokens.css` 集中定义两套语义颜色，暗色变量限定于屏幕，打印保持浅色。工作台首屏使用同源 `public/assets/theme-init.js`，报告初始化包含在 CSP 哈希验证的内嵌脚本中。

项目采用 [MIT License](../LICENSE)。生产资源包含 `dist/LICENSE.txt` 和 `dist/THIRD_PARTY_NOTICES.txt`，独立 HTML 报告内嵌项目及运行依赖的完整许可文本。

Formatly 是毕业论文与实习报告格式检测工具。本目录是 Vue 3 + Vite + TypeScript 前端。八种页面使用 hash 路由：`#new`、`#history`、`#job/<id>`、`#profiles`、`#plugins`、`#doctor`、`#schools[/<id>]`、`#collections[/<id>]`；侧栏按用户任务收敛为“新建检测、学校要求、检测记录、设置”，其他功能在所属页面内切换。新建检测先选择“预置方案”或“学校模板”：预置方案上传原稿后直接检测，学校模板上传成功后进入 `#schools/<id>` 核对要求。`#schools/new` 仍可在学校要求页新建一组。生成方案后进入带方案及类型参数的检测页，刷新、前进与后退保留路由中的选择。

页面通过 `src/api.ts` 访问 Python HTTP API。`useAuditStore` 管理任务详情、轮询、附件与方案，`useJobHistory` 管理历史搜索、筛选与分页，`useAuditSetup` 管理方案/类型/输入格式预检与集合选项，`useAuditFiles` 管理原稿校验及 DOCX 配对 PDF 状态，`useDocumentCapabilities` 管理 PDF/OCR 能力读取与刷新。`useSchoolWorkspace` 和 `useCollectionWorkspace` 分别管理学校依据与材料核验的异步状态及请求守卫。

`useDocumentScope` 管理当前原稿的临时预览和逐要求范围确认，`DocumentScopePicker` 展示真实 DOCX 样式、样段和分节。模板样式仅记录学校依据；检测时重新选择原稿范围，或明确暂不匹配以保留人工核对。文件、方案内容或材料类型变化会清除旧确认，提交同时校验原稿与方案哈希；任务创建成功后释放临时预览。没有范围要求的预置方案仍可直接检测。学校结构要求与普通方案编辑共用后端字段元数据和 `RuleFields`，本次范围选择只更新能力预览，是否符合要求以检测报告为准。

普通方案开始匹配后，须完成各项确认或明确退出，未完成和过期不会静默使用原方案。批量逐稿复用同一组件，切换保留选择，删除或替换文件安全失效，提交按原稿顺序携带独立绑定。方案复制与导入保留完整范围规则；学校副本记录原发布来源，不改变原方案。

开发与回归建议使用 Node.js 22 或更高版本：

```powershell
cd frontend
npm ci
npm test          # Node.js 内置测试运行器，验证前端行为
npm run typecheck
npm run dev       # 默认支持局域网访问，本机 http://127.0.0.1:5173
npm run build     # 构建工作台和独立报告模板到 dist
```

开发时另开终端，在项目根目录安装 `python -m pip install -r requirements.txt`，再运行 `python -m formatly serve --no-browser`。首次开发先运行 `npm run build` 准备报告模板，也可从根目录执行 `python start_dev.py` 一键启动后端与 Vite；`--local-only` 限定本机，`--no-browser` 关闭自动打开，`python start_dev.py stop` 停止该启动器管理的服务。Vite 默认监听 `0.0.0.0:5173`，API 代理目标为 `http://127.0.0.1:8765`，支持 `FORMATLY_DEV_HOST`、`FORMATLY_DEV_PORT`、`FORMATLY_API_TARGET` 配置。基础 PDF 解析依赖随主工具安装，可选 OCR 使用本机 Tesseract；`FORMATLY_TESSERACT` 指定程序路径，`FORMATLY_OCR_LANGS` 指定已安装语言组合（如 `chi_sim+eng`），缺少时由能力面板提示。前端使用 Composition API、TypeScript 和可复用组件，API 请求集中在 `src/api.ts`，任务状态、轮询和错误处理集中在 composables；检测规则由后端插件和 profile 提供。

学校材料流程由“学校依据”创建依据包开始：按论文、实习报告、证明类型上传 DOCX/PDF/TXT/MD/JSON 模板及说明，逐条核对候选来源和值，处理冲突、确认人工条款或有理由排除，再生成独立类型与版本的 profile。PDF 自动提取原生文本，扫描/混合页在本机 OCR 可用时识别；经核对的转录为可选校正覆盖，原件、自动提取、有效文本、元数据及覆盖哈希分别保留。`DocumentExtraction` 展示方法、页数、完整性和警告，OCR 不能替代人工确认。未确认、人工和不支持条款在报告中明确展示，排除不计自动通过。

“新建检测”接受 DOCX/PDF/TXT/MD/JSON，文档类型为 `thesis/intern/certificate`，包含证明基础方案 `certificate`。`src/utils/documents.ts` 共享扩展名与大小校验；更换方案、类型或原稿格式立即使此前的预检失效，迟到响应不能重新启用提交。非 DOCX 清空配对 PDF 并禁用 Word/WPS 渲染。通用方案可解析 DOCX 另附 PDF 的页面并核对可提取文字，但文字一致不认证版本或图表已配对。缺失依赖、格式/类型不匹配或仍在检查时禁止提交。

全站使用直接的功能标题，侧栏和页脚不重复展示运行说明。方案与插件介绍、哈希及完整配置放入折叠详情；具体错误、依赖缺失、未检查和待复核状态保持可见。上传页方案说明与 PDF 识别状态按需展开，识别异常时自动展开；选择 DOCX 后才提供“附加 PDF”，PDF 能力仅在原稿为 PDF 或已附 PDF 时检查，学校来源为 PDF 时才展示识别状态。

DOCX 检查实际样式和属性；PDF 检查可提取页面/文字，正文字体与字号需方案明确 `body.pdf_region_mm` 四边正文区域，未指定时仅给字体清单及人工复核，不推断 Word 样式、页边距或行距。TXT/MD/JSON 仅做文本结构与字段检查，无实际排版属性。普通 JSON 保留字符串字段路径；`formatly.document.v1` 支持标题、段落与明确字段，示例见 [examples](../examples/README.md)。

可选关联“材料核验”集合；集合按每个必需类型的最新任务比对姓名、学号、单位和起止日期证据。缺失、歧义、失败或未完成任务保持复核，不能用较早的成功任务替代当前失败任务；字段一致不代表签章或材料真实性认证。

结果页的“重试本次检测”使用任务保存的输入、规则和集合关联；“检测修改稿”只带入方案/类型/集合，必须重新选择实际文件。两种操作均建立新任务，不覆盖历史报告。

结果页还提供 DOCX“针对性修复”：`RepairPanel` 按需预览位置、实际值和目标值，默认不选，明确勾选后生成副本并进入复检任务。`useDocumentRepair` 管理预览、选择、提交互斥、错误及过期响应，API 仍集中在 `api.ts`。共享报告组件展示修复来源和应用数量，附件提供修复文档与修改记录；原任务及其报告保持原样。

报告展示也由此目录统一维护：`src/views/ResultView.vue` 与 `src/views/StandaloneReport.vue` 共用 `src/components/ReportContent.vue`、`IssueCard.vue`、`RuleCheckList.vue`、`StatusBadge.vue` 和 `src/utils/report.ts` 的证据格式化。工作台负责任务状态和附件，独立报告入口 `src/standalone-report.ts` 读取内嵌结果数据；两者共用报告内容和筛选搜索逻辑。

报告保留 `input_format/document_extraction`、`coverage.checks/summary/format_checks/complete`、学校条款来源、`profile_snapshot/profile_sha256`、引擎证据及实际格式原稿/可选 PDF 执行后完整性。七种检查状态为 `passed/failed/manual/not_checked/unsupported/error/not_applicable`。空规则或仅输入有效不等于格式通过；确认排除不计自动通过。`document_counts` 与数字 `execution_errors` 分别展示文档偏差及执行/完整性异常。历史结果缺少字段时显示已有计数并提示缺少覆盖证据，历史文件保持原样。

`npm run build` 先执行 Vite 工作台构建，再运行 `scripts/build-report.mjs`，将 Vue IIFE、CSS、透明图标 data URI 嵌入 `scripts/report.html`，输出 `dist/report-template.html`。Python `formatly/application/reports.py` 只安全注入 JSON 数据和导出 Markdown，不维护 HTML 布局或样式。独立 HTML 的核心内容、筛选和搜索不依赖网络或相邻文件，也不包含相对 JSON、Markdown 或方案链接；工作台保留完整附件下载。API 对 HTML 产物强制附件下载，不放宽工作台 CSP，历史报告不重写。

`GET /api/jobs` 使用服务端分页：接收 `q`、`status`、`limit`、`offset`，返回 `{items, total, stats, offset, limit}`。`total` 为筛选后总数，`stats` 为全库统计；列表摘要和详情分别保存。预检使用 `/api/profiles/<id>/preflight?kind=...&format=...`，能力使用 `/api/capabilities`；学校与集合使用 `/api/schools`、`/api/collections` 系列端点。API 与 CLI 共用同一业务服务；完整契约见 [前端架构与验收契约](ARCHITECTURE.md)，可执行示例见[根目录 README](../README.md)。

`public/assets/formatly-mark.png` 是透明背景品牌图标。工作台构建会清空 `frontend/dist`，再生成工作台资源和报告模板。修改前端或清除构建资源后，先执行 `npm test`、`npm run typecheck` 和 `npm run build`，再回到根目录运行 Python 单元测试与编译检查；HTML 导出测试依赖该模板。已有完整构建资源时可直接运行 Python，无需每次启动前重建。

生产工作台和报告生成需要 Python、主工具依赖与已构建资源，不需要 Node.js、Vite 服务或 CDN。`formatly/interfaces/http.py` 提供当前 HTTP API 并托管 `frontend/dist`；该目录中的资源及报告模板均由此 Vue 前端生成。日常运行保留 `frontend/dist/`。


所有前端内容统一位于本目录：`src/`、`public/`、`scripts/` 和 `dist/`。后端 `formatly/` 只含 Python 代码，并从相邻的 `frontend/dist` 读取构建资源。
