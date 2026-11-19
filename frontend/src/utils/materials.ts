import type { DocumentKind, Profile } from '../types'

export const documentKinds: { value: DocumentKind; label: string }[] = [
  { value: 'thesis', label: '毕业论文' },
  { value: 'intern', label: '毕业实习报告' },
  { value: 'certificate', label: '实习证明' }
]
export function kindLabel(kind?: string) { return documentKinds.find(item => item.value === kind)?.label || '文档类型未记录' }
export function profileLabel(profile: Profile) {
  if (!profile.school) return profile.name
  const version = profile.school.version ?? profile.version
  return `${profile.name} · ${typeof version === 'number' && Number.isInteger(version) && version > 0 ? `第 ${version} 版` : '学校版本未记录'}`
}
export function profileMatchesKind(profile: Profile, kind: string) {
  return !profile.kinds?.length || profile.kinds.includes(kind as DocumentKind)
}
const hiddenPresetIds = new Set(['campus-thesis', 'campus-intern', 'school-specific'])
export function isHiddenPreset(profile: Profile) {
  return hiddenPresetIds.has(profile.id)
}
const headingLevels = ['一', '二', '三', '四', '五', '六', '七', '八', '九'].map((label, index) => ({ level: index + 1, label: `${label}级标题` }))
const headingProperties = [
  ['fonts.eastAsia', '中文字体'], ['fonts.ascii', '基础拉丁文字字体'],
  ['fonts.hAnsi', '其他拉丁文字字体'], ['fonts.cs', '复杂文字字体'],
  ['size_pt', '字号（磅）'], ['alignment', '对齐方式'], ['before_lines', '段前距（行）'], ['after_lines', '段后距（行）']
]
export const automaticTargets: [string, string][] = [
  ['page.width_mm', '纸张宽度（毫米）'], ['page.height_mm', '纸张高度（毫米）'],
  ['page.margins_mm.top', '上边距（毫米）'], ['page.margins_mm.bottom', '下边距（毫米）'],
  ['page.margins_mm.left', '左边距（毫米）'], ['page.margins_mm.right', '右边距（毫米）'],
  ['body.font', '正文字体'], ['body.fonts.eastAsia', '中文字体'], ['body.fonts.ascii', '基础拉丁文字字体'],
  ['body.fonts.hAnsi', '其他拉丁文字字体'], ['body.fonts.cs', '复杂文字字体'],
  ['body.size_pt', '正文字号（磅）'], ['body.line_spacing', '自动行距（倍）'],
  ['body.style_ids', '正文样式标识列表'],
  ['paragraph.first_line_indent_chars', '段落首行缩进（字符）'], ['paragraph.before_lines', '段前间距（行）'],
  ['paragraph.after_lines', '段后间距（行）'], ['paragraph.line_spacing_pt', '段落固定行距（磅）'],
  ...headingLevels.flatMap(({ level, label }) => headingProperties.map(([path, property]): [string, string] => [`headings.${level}.${path}`, `${label}${property}`])),
  ['section.gutter_mm', '装订线（毫米）'], ['section.header_distance_mm', '页眉距边界（毫米）'],
  ['section.footer_distance_mm', '页脚距边界（毫米）'], ['section.columns', '分栏数量'],
  ['required_heading', '必备独立标题'],
  ['references.heading_after_lines', '参考文献标题段后距（行）'],
  ['references.entry_hanging_chars', '参考文献悬挂缩进（字符）'],
  ['references.citation_order', '参考文献引用顺序'],
  ['references.citation_unique', '参考文献不得重复引用'],
  ['field.name', '姓名'], ['field.student_id', '学号'], ['field.organization', '实习单位'],
  ['field.start_date', '开始日期'], ['field.end_date', '结束日期']
]

export function requiresStyleScope(target: string): boolean {
  return /^body\.(font|fonts\.[^.]+|size_pt|line_spacing)$|^paragraph\.(first_line_indent_chars|before_lines|after_lines|line_spacing_pt)$/.test(target)
}

export const automaticTargetGroups = [
  ['纸张与页边距', 'page.'], ['正文格式', 'body.'], ['段落排版', 'paragraph.'],
  ...headingLevels.map(({ level, label }) => [label, `headings.${level}.`]),
  ['分节与页眉页脚', 'section.'], ['必备标题', 'required_heading'], ['参考文献', 'references.'], ['材料字段', 'field.']
].map(([label, prefix]) => ({ label, targets: automaticTargets.filter(([target]) => target.startsWith(prefix)) }))
