# 配置与外部插件示例

这些数值和文本用于演示，不代表任何学校的正式要求。先按实际规范修改方案，再运行检测。

## 仅增加规则方案

在 Formatly 工具目录运行：

```powershell
python -m formatly profiles import examples/example-profile.json
python -m formatly check --input 'D:\材料\论文.docx' --profile my-school-example
```

`example-profile.json` 使用主工具内置插件，先安装主工具依赖（`python -m pip install -r requirements.txt`），无需另装示例插件。基础 PDF 解析使用已声明的 `pdfplumber`；扫描 OCR 另需本机 Tesseract 和实际使用的语言包。说明：

- 纸型和页边距单位为毫米，`tolerance_mm` 用于数值比较。
- `required_headings` 查找归一化后相同的独立段落，不使用包含匹配。
- `body.style_ids` 使用 DOCX 中实际的样式 ID，例如 `Normal`，不能直接假定界面上的中文样式名称就是 ID。
- `body.font` 是显式字体名称；`size_pt` 单位为磅；`line_spacing` 是自动行距的倍数。固定磅数行距、未解析字体及不明确属性保留待复核。
- 正文规则只作用于所选样式的非空段落；封面也使用该样式时，应先为正文建立独立样式，再配置其 ID。

上述样式、页边距和行距说明针对 DOCX；TXT/MD/JSON 没有这些排版属性，相关规则不能自动通过。PDF 可直接检查实际页面尺寸及原生文字，但不反推 Word 页边距、样式或行距。若要检查 PDF 正文字体/字号，须在方案 `settings.body` 中明确配置四个距页边缘的毫米值，例如：

```json
{
  "pdf_region_mm": {"top": 30, "bottom": 25, "left": 25, "right": 25},
  "fonts": {"eastAsia": "宋体", "ascii": "Times New Roman"},
  "size_pt": 12
}
```

这是 `settings.body` 的配置片段，只检查完全位于该区域的原生文字，不代表确认了实际页边距。未指定区域时提供字体清单并人工复核；扫描/OCR 文字也不用于确定字体或字号。

## 五种原稿与学校来源

`check --input` 与 `schools add-source --source` 均支持 DOCX、PDF、TXT、MD、JSON，复用同一读取与检测链路。选择原稿前可按格式预检：

```powershell
python -m formatly profiles preflight generic --kind thesis --format pdf
python -m formatly check --input 'D:\材料\论文.pdf' --profile generic --kind thesis
python -m formatly check --input 'D:\材料\论文.md' --profile generic --kind thesis
python -m formatly check --input examples/document.json --profile generic --kind thesis
python -m formatly schools add-source '学校依据包ID' --source 'D:\学校要求\说明.pdf' --kind thesis --role instructions
```

PDF 自动读取原生文字；扫描/混合页在本机 Tesseract 可用时补充识别，中文与英文识别需安装相应语言包。`FORMATLY_TESSERACT` 可指定程序完整路径，默认从 PATH 发现。默认语言优先 `chi_sim`，缺少时才使用 `eng`；中文模型也识别拉丁字符和数字，若要显式组合可设置 `FORMATLY_OCR_LANGS=chi_sim+eng` 并核对效果。程序不自动联网下载。Web 的能力面板、`/api/capabilities` 和 `formatly doctor` 会显示缺失原因。OCR 输出、学校数值和候选条款仍须人工核对。

学校 PDF 如需校正，可额外使用 `--transcription 'D:\学校要求\已核对文本.txt'`；这是有效文本覆盖，原件、原始自动提取、提取元数据及覆盖文件均分别保存并核验哈希。仅 DOCX 原稿可另附 `--pdf`；通用方案会解析页面并核对文字一致性，文字一致也不认证文件版本、图表或分页配对。

## JSON 文档示例

[document.json](document.json) 是原稿，不是方案配置；[document.schema.json](document.schema.json) 描述 `formatly.document.v1` 约束。结构化输入形如：

```json
{
  "schema": "formatly.document.v1",
  "title": "毕业实习报告",
  "paragraphs": [
    {"text": "实习内容", "role": "heading", "level": 1},
    {"text": "这里填写实际原稿正文。", "role": "body"}
  ],
  "fields": {
    "name": "示例姓名",
    "student_id": "示例学号",
    "organization": "示例单位",
    "start_date": "2027-01-01",
    "end_date": "2027-03-01"
  }
}
```

顶层仅支持 `schema/title/paragraphs/fields`；段落也可直接用字符串，对象段落需有 `text`，`role` 默认 body、可为 heading，`level` 如有提供则为 1–6。`fields` 仅支持上述五类字符串字段，不提供字体或页面属性。普通 JSON 无需 `schema`，递归提取字符串并保留 JSON Pointer，例如 `/fields/name`；数值、布尔值等不补成文字。重复键、非有限数值、未知 schema、结构错误、超过 40 层/5 万项或超限输入会拒绝。JSON 原始文件限 2MiB，解码后的整个 JSON 文本及提取正文分别限 1MiB（按 UTF-8 字节计）。`profiles import` 继续只处理规则方案，不能把文档 JSON 导入为方案。

## 安装独立插件

先安装主工具依赖，再安装示例插件，二者必须安装到启动 Formatly 的同一个 Python 环境：

```powershell
python -m pip install -r requirements.txt
python -m pip install -e examples/example-plugin
python -m formatly plugins list
python -m formatly profiles import examples/plugin-profile.json
python -m formatly check --input 'D:\材料\论文.docx' --profile placeholder-example
```

已运行的 Web 服务安装插件后需要重启。插件通过 `formatly.plugins` 入口组发现，入口值指向无参数工厂或类。无需修改主工具的注册表或 Web 页面。

示例使用 `formatly.domain` 等主工具接口，检查 DOCX 中指定的占位文本，并在自己的 `example-placeholders/` 目录保存证据。该示例不因此支持 PDF/TXT/MD/JSON；外部插件应通过 `formats` 只声明实际实现的格式，未声明时按仅 DOCX 处理。可以修改其规则、创建新插件 ID，再把该 ID 加入方案的 `plugins` 数组。

配置错误和插件异常会由统一流水线记为运行不完整；示例发现占位文本时默认产生警告，不把提示当成学校格式错误。

