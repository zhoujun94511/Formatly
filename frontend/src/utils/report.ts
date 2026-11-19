import { automaticTargets } from './materials'
import type { Issue } from '../types'

const evidenceLabels: Record<string, string> = {
  font: '字体', fonts: '字体', size: '字号', size_pt: '字号（磅）', line_spacing: '行距（倍）',
  eastAsia: '中文字体', ascii: '西文字体', hAnsi: '其他西文字体', cs: '复杂文字字体',
  width_mm: '宽度（毫米）', height_mm: '高度（毫米）', margins_mm: '页边距（毫米）',
  top: '上', bottom: '下', left: '左', right: '右', before: '段前', after: '段后',
  value: '数值', expected: '要求', actual: '实际', text: '文本', reason: '说明',
  line: '行距', lineRule: '行距类型', hanging: '悬挂缩进', hangingChars: '悬挂缩进（字符）',
  count: '数量', page: '页码', location: '位置', method: '读取方式', complete: '是否完整',
  source: '依据', name: '名称', status: '状态', paragraph: '段落', style: '样式',
  paper: '纸张', spacing: '间距', unit: '单位', minimum: '最小值', maximum: '最大值',
  font_name: '字体名称', font_size: '字号', alignment: '对齐方式', indent: '缩进',
  provenance: '属性来源', direct: '直接设置', inherited: '样式继承', effective: '有效格式',
  rule: '类型', points: '磅', side: '方向', gutter_mm: '装订线（毫米）',
  header_distance_mm: '页眉距边界（毫米）', footer_distance_mm: '页脚距边界（毫米）',
  first_line_indent_chars: '首行缩进（字符）', before_lines: '段前（行）', after_lines: '段后（行）',
  line_spacing_pt: '固定行距（磅）',
  lines_per_page: '每页行数', characters_per_line: '每行字符数', columns: '栏数',
  chinese_title_size_pt: '中文标题字号（磅）', chinese_title_font: '中文标题字体', body_size_pt: '正文字号（磅）',
  level_1_size_pt: '一级标题字号（磅）', level_2_size_pt: '二级标题字号（磅）', level_3_size_pt: '三级标题字号（磅）',
}
const evidenceValues: Record<string, string> = {
  unresolved_table_style: '表格样式影响尚需核对', unresolved: '尚无法确定',
  auto: '自动', exact: '固定值', atLeast: '最小值', passed: '通过', failed: '不符合',
  manual: '待复核', not_checked: '未执行', unsupported: '不支持', error: '检查失败',
  left: '左侧', right: '右侧', center: '居中', both: '两端对齐',
}
export function displayEvidence(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未记录'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) return value.map(displayEvidence).join('、') || '无'
  if (typeof value === 'object') return Object.entries(value).map(([key, entry]) => `${evidenceLabels[key] || key}：${displayEvidence(entry)}`).join('\n') || '无'
  return evidenceValues[String(value)] || String(value)
}

export function displayFormatEvidence(value: unknown): string {
  if (Array.isArray(value)) return value.map(displayFormatEvidence).join('、') || '无'
  if (value && typeof value === 'object') return Object.entries(value).map(([key, entry]) => `${evidenceLabels[key] || '其他属性'}：${displayFormatEvidence(entry)}`).join('\n') || '无'
  return displayEvidence(value)
}

function canonicalRuleTarget(id?: string): string {
  return (id || '').replace(/^page\.margin\.(top|bottom|left|right)$/, 'page.margins_mm.$1')
}

const ruleUnits: [RegExp, string][] = [
  [/^(body\.size_pt|paragraph\.line_spacing_pt|headings\.[1-9]\.size_pt)$/, '磅'],
  [/^body\.line_spacing$/, '倍'],
  [/^(paragraph|headings\.[1-9])\.(before_lines|after_lines)$/, '行'],
  [/^paragraph\.first_line_indent_chars$/, '字符'],
  [/^section\.columns$/, '栏'],
  [/^page\.(width_mm|height_mm|margins_mm\.(top|bottom|left|right))$|^section\.(gutter_mm|header_distance_mm|footer_distance_mm)$/, '毫米'],
]

export function displayRuleEvidence(value: unknown, id?: string): string {
  const target = canonicalRuleTarget(id)
  if (/^headings\.[1-9]\.alignment$/.test(target) && typeof value === 'string') {
    const alignment: Record<string, string> = { left: '左对齐', center: '居中', right: '右对齐', both: '两端对齐' }
    if (alignment[value]) return alignment[value]
  }
  const formatted = displayFormatEvidence(value)
  if (typeof value !== 'number' || !Number.isFinite(value)) return formatted
  const unit = ruleUnits.find(([pattern]) => pattern.test(target))?.[1]
  return unit ? `${formatted} ${unit}` : formatted
}

export function ruleLabel(id?: string): string {
  const names: Record<string, string> = {
    'body.font': '正文字体', 'body.size_pt': '正文字号', 'body.line_spacing': '正文行距',
    'body-font-size': '正文字号', 'page.width_mm': '纸张宽度', 'page.height_mm': '纸张高度',
    'structure.heading': '必需章节', 'layout.visual_review': '页面效果复核',
    'package.valid': '文档文件检查', 'document.valid': '文档文件检查',
    'extraction.review': '文字提取复核', 'docx.content_review': '文档内容复核',
  }
  return automaticTargets.find(([target]) => target === canonicalRuleTarget(id))?.[1] || names[id || ''] || (id?.startsWith('page.margin') ? '页边距' : '格式检查')
}

export function issueTitle(issue: Issue): string {
  return issue.message === '格式属性与所选方案不符' ? ruleLabel(issue.rule_id) : issue.message || ruleLabel(issue.rule_id)
}

export function displayLocation(value: unknown): string {
  return displayEvidence(value)
    .replace(/^XML段(\d+)(?=[:：\s]|$)/, '第 $1 段')
    .replace(/\/\s*run(\d+)(?=\s*(?:\/\s*(?:eastAsia|ascii|hAnsi|cs))?\s*$)/, '／第 $1 处文字')
    .replace(/\/\s*(eastAsia|ascii|hAnsi|cs)\s*$/, (_match, key: string) => `／${evidenceLabels[key]}`)
}

export function engineLabel(id?: string, name?: string): string {
  if (name && /[\u3400-\u9fff]/.test(name)) return name
  return ({ generic: '通用格式检测', 'generic-format': '通用格式检测', portable: '多格式检测',
    'portable-text': '多格式文本检测', 'docx-package': '文档文件检查', 'document-fields': '材料字段核对', 'academic-format': '论文与报告排版',
    legacy: '可选外部专项引擎', 'legacy-school': '可选外部专项引擎', core: '检测服务' } as Record<string, string>)[id || ''] || '检测组件'
}

export function sourceEntries(value: unknown): unknown[] {
  return Array.isArray(value) && value.length ? value : [value]
}

export function displaySource(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return displayEvidence(value)
  const source = value as Record<string, unknown>
  if (typeof source.source_id !== 'string') return displayEvidence(value)
  const school = source.school && typeof source.school === 'object' ? source.school as Record<string, unknown> : undefined
  const files = Array.isArray(school?.sources) ? school.sources as Record<string, unknown>[] : []
  const file = files.find(item => item.id === source.source_id)
  const title = [school?.name, file?.filename || source.source_id, source.locator].filter(value => typeof value === 'string' && value).join(' · ')
  return source.excerpt ? `${title}：${String(source.excerpt)}` : title
}

