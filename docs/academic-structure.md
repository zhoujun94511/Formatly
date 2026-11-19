# 论文与报告结构检测

`academic-structure` 是内置的独立规则包。用户按学校已确认的要求选择规则；未配置的项目不执行，也不从学校名称推断规范。Web、CLI 和 Python 调用使用同一业务服务。它补充标题结构、图表题引用、文献对应和页码设置，不重复通用插件的必需章节、引用首次顺序或重复引用检查。

## 配置

在方案中启用 `academic-structure` 并设置 `settings.structure`：

```json
{
  "id": "structure-example",
  "name": "匿名结构规则示例",
  "plugins": ["docx-package", "academic-structure"],
  "settings": {
    "structure": {
      "headings": {"hierarchy": true, "chapter_page_break": true, "chapter_level": 1},
      "captions": {
        "style_ids": ["Caption"],
        "figure_label": "图",
        "table_label": "表",
        "numbering": "continuous",
        "start": 1,
        "require_reference": true
      },
      "references": {"heading": "参考文献", "correspondence": true, "require_all_cited": true},
      "page_numbers": {"require_field": true, "format": "decimal", "start": 1, "section_indices": [2]}
    }
  }
}
```

示例不是学校正式标准。`Caption` 应替换为原稿中已确认的题注样式 ID。页码默认核验全部活动分节；`section_indices` 是从 1 开始的目标分节序号。`start` 可以填写正整数或 `"continue"`（接续前节）；`format` 支持 `decimal`、`lowerRoman`、`upperRoman`、`lowerLetter`、`upperLetter`。

## 证据与边界

| 项目 | 可核对的事实 | 保留人工处理的情况 |
| --- | --- | --- |
| 标题层级 | 大纲级别或标准标题样式继承；首个标题应为一级，后续向下最多一级 | 范围不明确、隐藏或修订内容未确认；不从外观或正文关键词猜级别 |
| 章前分页 | 有效 `pageBreakBefore`、文字前或前段末尾的分页符、活动分页分节；首个正文位置单独识别 | 表格内标题或未知属性；缓存的 `lastRenderedPageBreak` 不作为分页设置证明 |
| 图表题编号 | 已确认题注样式内的标签和数字；图、表分别连续编号，或按 `chapter` 前缀各自连续编号 | 未声明样式范围、题注歧义、动态域或未确认正文；前缀与实际章号对应另行复核 |
| 图表引用 | 题注是否被正文引用，以及正文引用是否缺少对应题注 | 省略或范围写法、图形或隐藏文字承载的引用；题注自身不当作正文引用 |
| 文献对应 | 唯一参考文献标题之前为正文；数字引用对应 `[n]` 条目；重复条目与未引用条目 | 作者年份体系、跨段续行、章节边界不明确、脚注／尾注或提取不完整；不推断文献真实性 |
| 页码域和分节 | 内部关系、默认及奇偶页眉页脚中的完整 `PAGE` 域、关系继承、显式节格式和起始值 | 外部或损坏关系、未闭合域、隐藏／修订域、缺少显式格式；正文数字和 `NUMPAGES` 不是当前页码域 |

这些规则读取 DOCX 结构。PDF、TXT、MD 和 JSON 不具有同等 Word 结构契约，逐项返回“不支持”。实际分页、首页页码、域刷新后的显示、目录一致性和打印效果保留独立人工检查。结构规则只检测，不向文档写入章节、题注或页码域。

## 固定兼容性集

`tests/fixtures/academic_structure_cases.json` 独立保存10份匿名XML原始输入和35项状态标注，覆盖正反例、题注范围、图表分别编号、悬空引用、数字引用范围、文献缺项、未引用条目、复杂 `PAGE` 域和节配置缺失。

```powershell
# Windows
.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_academic_structure.py -q
.venv\Scripts\python.exe -B scripts/evaluate_academic_structure.py --output .verification/academic-structure
```

```bash
# macOS / Linux
.venv/bin/python -B -m unittest discover -s tests -p test_academic_structure.py -q
.venv/bin/python -B scripts/evaluate_academic_structure.py --output .verification/academic-structure
```

独立评测经共享服务生成任务和报告，`summary.json` 保留 fixture、输入、规则、gold、报告摘要及逐规则状态，并实测耗时和 Python 分配峰值。失败返回非零退出码。本组不并入历史学校准确率分母，也不代替真实学校全量专家验收。
