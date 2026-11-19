# 论文与报告排版插件

Formatly 内置 `academic-format` 插件，在本机直接读取 DOCX 的排版属性。它与已有的纸张、页边距、正文字体、字号、倍数行距、参考文献和材料字段检查共用文档读取器、任务流水线和报告，无需配置外部专项工具或启动 Word。

## 使用

在“规则方案”复制“论文与报告 · 排版检查”，启用“论文与报告排版”，按学校规范填写参数后保存；新建检测时选择保存的方案。默认方案仅含 A4、单栏等明确列出的参数，其他学校要求应填写后再检测。

也可在“学校要求”上传模板与说明，核对提取的目标、数值和适用样式后确认。确认后的原生排版条款会编入方案，报告逐项关联该条款的实际检查。自动提取不代替人工确认学校要求。

## 范围

| 检查项目 | 参数 | 读取依据 |
| --- | --- | --- |
| 正文首行缩进 | `paragraph.first_line_indent_chars` | 百分之一字符单位的首行设置 |
| 正文段前、段后 | `paragraph.before_lines`、`after_lines` | 段距行数设置；自动段距或不能换算的磅数保留复核 |
| 正文固定行距 | `paragraph.line_spacing_pt` | 固定行距的磅数；与倍数、最小行距区分 |
| 各级标题中西文字体 | `headings.<级别>.fonts` | 可确定的标题级别及实际文字字体槽 |
| 各级标题字号、对齐、段距 | `headings.<级别>.size_pt/alignment/before_lines/after_lines` | 样式与直接格式的有效属性 |
| 装订线 | `section.gutter_mm` | 有效分节的装订线尺寸，不替代左页边距 |
| 页眉、页脚距边界 | `section.header_distance_mm`、`footer_distance_mm` | 有效分节的页面设置，不等于核对页眉正文或实际页码 |
| 栏数 | `section.columns` | 有效分节的栏设置 |

标题级别为 1–9。没有可确定的标题、找不到指定正文样式、文字属性存在不确定性时保留人工复核；不根据标题文字、中文样式名或近似尺寸猜测。

正文段落必须通过 `paragraph.style_ids` 明确范围；学校条款也可分别指定 `scope_style_ids`，编译后保存在 `paragraph.property_style_ids`。封面、摘要、目录、标题和图表题不会因为共用某个样式就自动当作正文。使用相同正文范围的固定行距与倍数行距不得作为相互矛盾的要求保存。

PDF、TXT、MD、JSON 仍可提交使用该插件的方案；其中未承载的 Word 排版属性明确记为不支持，不会被算作已通过。其他插件继续执行可支持的页面、内容和字段检查。

## JSON 示例

以下只是参数示例，不代表任何学校的正式标准。`BodyText` 应替换为文档中经确认的正文样式 ID。

```json
{
  "id": "academic-example",
  "name": "论文排版示例",
  "version": 1,
  "kinds": ["thesis", "intern"],
  "plugins": ["docx-package", "generic-format", "academic-format", "document-fields"],
  "settings": {
    "page": {"width_mm": 210, "height_mm": 297},
    "paragraph": {
      "style_ids": ["BodyText"],
      "first_line_indent_chars": 2,
      "before_lines": 0,
      "after_lines": 0,
      "line_spacing_pt": 20
    },
    "headings": {
      "1": {"fonts": {"eastAsia": "黑体"}, "size_pt": 16, "alignment": "center"}
    },
    "section": {"gutter_mm": 10, "header_distance_mm": 20, "footer_distance_mm": 20, "columns": 1}
  }
}
```

CLI 导入此方案后使用同一服务：

```powershell
python -m formatly profiles import academic-example.json
python -m formatly profiles preflight academic-example --kind thesis --format docx
python -m formatly check --input 'C:\Documents\sample.docx' --profile academic-example --kind thesis
```

## 报告与修改

报告列出要求值、实际值和 XML 段落或分节位置，已确定的主文档节点可通过现有证据入口查看。没有匹配段落的检查不会因零条问题而被当作合格。

检测到不符合且位置、要求和实际值均明确时，可选择修复首行字符缩进、段前段后行数、固定行距，以及标题字体、字号、对齐和段距。分节的装订线、页眉和页脚距离也可生成候选，写入时同时校验页面的有效正文空间。学校方案中的段落属性必须匹配已确认条款的样式范围。候选仅来自内置插件在原件上的重新检测；生成新 DOCX 副本后，使用相同方案完整复检，保留原件和逐项修改清单。

分栏宽度与布局、悬挂缩进冲突、无法明确读取的主题字体、复杂文字独立字号、无法准确表达的单位数值，以及保护、签名或修订文档不自动修改。应根据位置和数值在 Word/WPS 中修改，再上传复检。

实际分页、目录页码一致性、页眉文字、签章、图表视觉位置和复杂摘要版式仍需相应页面证据或人工核对。可选外部工具的接法见[外部引擎接入](external-engines.md)，它不是使用此内置插件的前提。

属性单位与大纲级别遵循公开 WordprocessingML 定义：[首行字符缩进](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.indentation.firstlinechars?view=openxml-3.0.1)、[段前行数](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.spacingbetweenlines.beforelines?view=openxml-3.0.1)、[行距单位](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.spacingbetweenlines.line?view=openxml-3.0.1)、[大纲级别](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.outlinelevel?view=openxml-3.0.1)。
