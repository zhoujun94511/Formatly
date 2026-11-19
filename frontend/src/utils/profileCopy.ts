import type { Profile } from '../types'

function canonical(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']'
  if (value && typeof value === 'object') return '{' + Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
    .map(([key, part]) => JSON.stringify(key) + ':' + canonical(part)).join(',') + '}'
  return JSON.stringify(value) ?? 'null'
}

function copyValue<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T }

export function profilePlugins(source: Profile): string[] {
  return [...new Set(['docx-package', ...(source.plugins || [])])]
}

function rulesChanged(source: Profile, settings: unknown, plugins: string[]): boolean {
  return canonical(source.settings || {}) !== canonical(settings)
    || canonical(profilePlugins(source)) !== canonical(plugins)
}

export function schoolRulesChanged(source: Profile, settings: unknown, plugins: string[]): boolean {
  return !!source.school && rulesChanged(source, settings, plugins)
}

export function profileCopy(source: Profile, fields: Profile): Profile {
  const preserveConfirmation = !rulesChanged(source, fields.settings || {}, fields.plugins || [])
  if (!preserveConfirmation && !source.school && source.scoped_rules?.length) {
    throw Error('此方案含分范围规则。此处可修改名称和说明；规则调整请编辑完整方案 JSON 后重新导入。')
  }
  const school = source.school ? { ...source.school,
    source_profile_id: source.school.source_profile_id || source.id } : undefined
  return { ...fields, ...(source.kinds ? { kinds: [...source.kinds] } : {}),
    ...(preserveConfirmation && school ? { school } : {}),
    ...(preserveConfirmation && source.requirements ? { requirements: copyValue(source.requirements) } : {}),
    ...(preserveConfirmation && source.scoped_rules ? { scoped_rules: copyValue(source.scoped_rules) } : {}) }
}
