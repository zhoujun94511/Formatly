# Formatly 文档格式与提取规范

学校依据和待检原稿使用同一文档读取器，支持 DOCX、PDF、TXT、MD、JSON。检测依据是原稿实际承载的内容和属性，任何缺失属性都不能通过格式转换补造。

## 格式与证据

| 格式 | 提取结果 | 可用检查 |
| --- | --- | --- |
| DOCX | 文本、段落、明确样式与页面属性、位置证据 | 包结构、页面配置、配置范围内的正文、独立标题、标签字段 |
| PDF | 页码、原生文本、字形、坐标、纸型、表格和可选 OCR | 页面尺寸、内容、明确正文区域内原生文字的字体与字号、标题和字段 |
| TXT / MD | 解码文本、文本位置、标题与标签字段 | 内容结构及字段；不推断实际纸张或排版 |
| JSON | 字符串、结构化段落与字段、JSON Pointer | 标题、内容与明确字段；不推断字体或纸张 |

`formatly/documents/reader.py` 为共享读取入口，PDF 解析由隔离进程 `formatly/documents/worker.py` 执行；`plugins/portable.py` 按非 DOCX 证据执行通用规则。学校来源、待检原稿、配对 PDF 与字段插件使用相同的提取语义。

## DOCX 内容与属性

DOCX 直接读取 Office Open XML 的 WordprocessingML 属性，使用通用 Office 单位和术语：页面尺寸与边距按二十分之一磅换算毫米，字号按半磅换算磅；`w:lineRule="auto"` 的 `w:line` 按 240 分之一行解释，`exact` 和 `atLeast` 按二十分之一磅解释。因此 `line=360` 在 `auto` 下是 1.5 倍，在 `exact` 下是固定 18 磅，两者不能互换。定义参见 Microsoft 的[页面尺寸](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.pagesize)、[字号](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.fontsize)和[行距](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.spacingbetweenlines.line)说明。倍数行距由正文规则检查，固定磅数由 `academic-format` 的 `paragraph.line_spacing_pt` 检查并可选择修复；同一范围的两种行距不能同时配置，`atLeast` 不当作固定值通过。

原稿使用 Word/WPS 保存的标准 DOCX，无需嵌入 Formatly 字段。样式 ID 仅在当前文档内解释，不能假定 `1`、`Normal` 或 `BodyText` 在所有文档中代表同一范围。规则方案 JSON 属于检测工具配置，与原稿文件格式分开管理。

`formatly/documents/docx_semantics.py` 统一解释 DOCX 的有效内容、样式继承和字符属性，供学校候选、正文检查、标题、字段与修复观察使用。文档默认值、段落/字符样式及直接属性按层合并，保留原 XML 段落与文本片段索引，避免排除内容后位置漂移。

隐藏文字不用于标题、字段或格式通过判断；删除/移出修订被排除，插入/移入修订作为当前内容读取，均保留修订视图复核提示。`AlternateContent` 的显示分支未经确认时不合并其文本，保留人工复核；此处理不模拟 Word/WPS 最终显示与打印。

`cs/rtl` 可使字符使用复杂文字字体槽和 `szCs` 字号。主题字体、含歧义的字体选择或无法确定的混合字号不能判为符合。`formatly/documents/fonts.py` 为 DOCX/PDF 共用已知字体族名称比较，例如宋体与 SimSun 等价，宋体与黑体不等价；原始字体名称继续保留为证据，字体族比较不验证实际字形或分页。

学校正文要求以 `scope_style_ids` 保存已核对的段落样式范围，按各属性编译到方案的 `body.property_style_ids`。未确认范围时保留人工复核，不用 `Normal` 封面或其他非正文样式推导正文已符合；原稿采用其他样式时须先核对并调整范围。

参考文献规则也通过学校确认的 profile 执行。`settings.references` 可分别配置 `heading_after_lines`（参考文献标题段后距）、`entry_hanging_chars`（条目悬挂缩进字符数）、`citation_order: "ascending"`（正文引用首次出现顺序从起始编号递增）和 `citation_unique: true`（禁止重复引用），并可指定 `entry_style_ids`、`citation_start` 与标题文本。DOCX 会保留段落定位、实际 twips、字号和换算后的字符数；PDF、TXT、MD、JSON 不保存 Word 段落间距和悬挂缩进，因此这些属性标记为 `unsupported`/人工复核，但可对完整文本核对引用顺序和重复编号。字符数与厘米值的换算必须以学校确认口径为准，报告会同时保留原始单位证据。

规则方案是可持久化的独立配置。内置方案只读，学校确认会按论文、实习报告和实习证明生成带版本的方案；用户也可以保存多套自定义 JSON 方案。Web“新建检测”页面通过下拉列表选择方案并执行类型、格式和插件预检，任务和报告保存所选方案的完整快照；CLI 使用 `--profile` 选择同一方案。不同方案不会共享运行时状态。

## PDF 与 OCR

PDF 基础解析使用 `pdfplumber`，页面预览和扫描页渲染使用 `pypdfium2` 与 `Pillow`。扫描页和混合页在本机 Tesseract 可用时补充识别，保留原生或 OCR 方法、页码、范围、置信度与复核标志。人工校正文本可用作有效文本覆盖，自动提取证据仍保存。

OCR 程序默认从 PATH 发现，`FORMATLY_TESSERACT` 可指定程序路径。默认优先已安装的 `chi_sim`，没有时使用 `eng`；`FORMATLY_OCR_LANGS` 可配置已安装的语言组合。程序和语言包不会自动下载，缺失时明确提示。中文内容不能依靠英文模型获得可靠结论。

PDF 正文字体和字号比较需要 `settings.body.pdf_region_mm` 显式指定上、下、左、右范围，单位为毫米。只检查完全位于该区域的原生文字；选定区域不等于 Word 页边距，OCR 结果不能证明原字体。

单份 PDF 最多处理 300 页、最多 OCR 20 页。超时、部分页面不可读、OCR 不可用或超出边界时，提取保持不完整或待复核状态。识别到签章文字不等于签章真实。

## JSON 文档

普通 JSON 递归提取字符串及明确标签字段，使用 JSON Pointer 定位，例如 `/fields/name`。数值和布尔值不自动补成正文。

结构化材料使用 `formatly.document.v1`，示例与本地约束分别为 [document.json](../examples/document.json) 和 [document.schema.json](../examples/document.schema.json)。顶层为 `schema`、`title`、`paragraphs`、`fields`；段落可为字符串或带 `text` 的对象，`role` 为 `body` 或 `heading`，标题级别为 1–6。字段支持姓名、学号、单位、起止日期，不声明字体、纸张或签章属性。

`fields` 可省略。显式提供字段表（包括 `{}`）时，已启用的必填字段规则可以核对缺键、空白或未填写占位符，并定位到实际字段或 `/fields` 父对象。字段表缺键但正文有明确值时采用正文证据；字段表空值与正文有值、两处值冲突、非空非法日期或无法解释的值均需人工核对。普通正文默认不能仅凭没有匹配到标签就认定缺项。签字盖章仍需人工核验。

## 必填标签表单

方案的 `settings.fields.missing_policy` 默认为 `review`。DOCX、原生PDF、TXT、MD、结构化JSON中确有空标签、未填写占位或明确空表格值时，可按实际位置报告问题；标签后的换行可能还有值、另一处有冲突值或提取不足时保留复核。

仅当原稿明确约定按字段标签填写时，可在复制方案的“缺项处理”选择“完整标签表单缺项时报告错误”（`fail_when_complete`）。正文文字覆盖充分时，未出现必填标签可报告缺项，证据记录全文检查范围；不虚构缺项所在段落。此选项不证明学校要求这种填写布局，仍需使用者按实际材料确认。

`field_text_coverage` 独立记录全文范围是否充分。OCR、辅助或不确定文字、DOCX图片/未读取部件、Markdown内嵌内容、PDF图形对象或未知对象计数等会阻止缺标签强判。读取完成不等于所有可见信息均已解释。

重复键、非有限数值、未知版本、结构不符、超过 40 层或 5 万项的结构均被拒绝。JSON 文档与规则方案是两种输入，`profiles import` 只用于规则方案。

## 输入与完整性

原稿及学校来源单文件上限为 40MiB，提取正文上限为 1MiB。JSON 原始文件另限 2MiB，其解码后的全文及提取正文分别受 1MiB UTF-8 字节限制。

仅 DOCX 原稿可另附配对 PDF 或使用可选的[本机 Word/WPS 导出](office-rendering.md)。配对检查核对可提取文字，文字相同不能证明图表、版本或分页完全一致。PDF 原稿不接受另一份配对 PDF。工作台替换或移除主稿时同步清空已选配对 PDF 及其错误，即使新主稿仍为 DOCX 也须重新选择配对文件。

每个任务保留实际格式的输入、请求和规则快照，并复核执行前后哈希；CLI 另核对用户原件。输入变化、提取不完整和执行异常必须影响报告结论。

## 验证要求

测试样例应覆盖五格式 HTTP/CLI、快照与重试、原稿变化、JSON 边界、中文原生 PDF、扫描及混合页、正文区域规则和不支持属性，以及 DOCX 隐藏/修订/互斥分支、字体别名、复杂文字属性和学校正文范围。前端应检查格式选择、能力提示、预检禁用、主稿替换后的配对清空、OCR 来源展示和报告完整性。

真实学校准确率、独立 HTML 的本地文件打开效果、外部专项和干净机器安装，需要对应环境及业务材料单独验收。
