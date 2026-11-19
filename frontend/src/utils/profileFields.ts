import type { Profile } from '../types'

export interface RuleField { path: string; label: string; group: string; type: 'number' | 'text' | 'lines' | 'select' | 'boolean'; options?: { value: string; label: string }[]; const_options?: { value: string; label: string }[]; integer?: boolean; unit?: string; minimum?: number; exclusiveMinimum?: number; maximum?: number; placeholder?: string; help?: string; value_schema?: Record<string, unknown> }
export interface RuleFieldGroup { plugin_id: string; fields: RuleField[] }
export interface DocumentFieldOptions { plugin_id: string; field_options: { value: string; label: string }[]; missing_policies: { value: string; label: string }[]; missing_policy_help: string }
export interface FontComparison { kind: 'font_family'; aliases: Record<string, string>; families: string[]; suffixes: string[] }
export interface SchoolTargetField { target: string; label: string; plugin_id: string; type: RuleField['type']; value_schema: Record<string, unknown>; parameter_fields: RuleField[]; parameters_schema: Record<string, unknown>; scope: 'styles' | 'sections' | 'global'; allow_global_scope: boolean; comparison?: FontComparison; options?: { value: string; label: string }[]; const_options?: { value: string; label: string }[] }
export interface ProfileFields extends RuleFieldGroup { schema_version: number; academic_fields?: RuleFieldGroup; structure_fields?: RuleFieldGroup; document_fields?: DocumentFieldOptions; school_targets?: SchoolTargetField[] }

export function requirementComparisonValue(value: unknown, field?: SchoolTargetField): unknown {
  const rules = field?.comparison
  if (rules?.kind !== 'font_family' || typeof value !== 'string' || !value.trim() || value.trim().toLowerCase() === 'unknown') return value
  let name = value.replace(/^[A-Z]{6}\+/, '').replace(/[\s,_-]/g, '').toLowerCase()
  if (/^(?:f|font|cidfont)\d+$/.test(name)) return value
  name = Object.hasOwn(rules.aliases, name) ? rules.aliases[name] : name
  return rules.families.find(family => rules.suffixes.some(suffix => name === family + suffix)) || name
}

export function requirementValue(text: string, field: SchoolTargetField): unknown {
  let value: unknown = text.trim()
  const alternatives = Array.isArray(field.value_schema.anyOf) ? field.value_schema.anyOf as Record<string, unknown>[] : []
  const constant = alternatives.find(schema => 'const' in schema && String(schema.const) === value)
  if (constant) return constant.const
  const schema = alternatives.find(schema => schema.type === 'integer' || schema.type === 'number') || field.value_schema
  if (field.value_schema.type === 'null' || (Array.isArray(field.value_schema.type) && field.value_schema.type.includes('null')) && (!value || value === 'null')) value = null
  else if (field.type === 'number') {
    if (!value) throw Error(`${field.label}必须填写有效数字。`)
    value = Number(value)
    if (typeof value !== 'number' || !Number.isFinite(value)) throw Error(`${field.label}必须填写有效数字。`)
    if ((schema.type === 'integer' || schema.integer === true) && !Number.isInteger(value)) throw Error(`${field.label}必须填写整数。`)
    if (typeof schema.minimum === 'number' && value < schema.minimum || typeof schema.maximum === 'number' && value > schema.maximum || typeof schema.exclusiveMinimum === 'number' && value <= schema.exclusiveMinimum) throw Error(`${field.label}超出允许范围。`)
  } else if (field.type === 'boolean') {
    if (value !== 'true' && value !== 'false') throw Error(`${field.label}请选择启用或关闭。`)
    value = value === 'true'
  } else if (field.type === 'lines') {
    try { value = JSON.parse(text) } catch { value = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean) }
    if (!Array.isArray(value) || value.some(item => typeof item !== 'string' || !item.trim())) throw Error(`${field.label}应为非空字符串列表。`)
    value = [...new Set((value as string[]).map(item => item.trim()))].sort()
  }
  if (Array.isArray(field.value_schema.enum) && !field.value_schema.enum.includes(value)) throw Error(`${field.label}请选择有效选项。`)
  return value
}
export type ExpectedCapability = 'conditional' | 'manual' | 'unsupported' | 'excluded' | 'unavailable'
export interface EffectiveSummary {
  profile_id: string; profile_name: string; version: number; kind?: string | null; input_format: string
  source: { name: string; version?: number | null }
  items: { id?: string; requirement_id?: string; target: string; label: string; expected?: unknown; state: ExpectedCapability; reason: string; scope?: unknown; scope_type?: string }[]
  counts: Record<ExpectedCapability, number>; disclaimer: string
}

export function settingsObject(text: string): Record<string, unknown> {
  const value: unknown = JSON.parse(text)
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('规则参数必须是 JSON 对象。')
  return value as Record<string, unknown>
}

export function updateDocumentFieldRules(text: string, metadata: DocumentFieldOptions, patch: { required?: string[]; missing_policy?: string }): string {
  const settings = settingsObject(text)
  const current = settings.fields
  if (current !== undefined && (!current || typeof current !== 'object' || Array.isArray(current))) throw Error('fields 必须为对象，请先修正高级参数。')
  const fields = { ...(current as Record<string, unknown> | undefined) }
  if (patch.required !== undefined) {
    if (patch.required.some(value => !metadata.field_options.some(option => option.value === value))) throw Error('必填字段无效。')
    fields.required = [...new Set(patch.required)]
  }
  if (patch.missing_policy !== undefined) {
    if (!metadata.missing_policies.some(option => option.value === patch.missing_policy)) throw Error('缺项处理方式无效。')
    fields.missing_policy = patch.missing_policy
  }
  settings.fields = fields
  return JSON.stringify(settings, null, 2)
}

export function fieldValue(settings: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce<unknown>((value, key) => value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)[key] : undefined, settings)
}

export function updateRuleField(text: string, field: RuleField, raw: string): string {
  const parts = field.path.split('.')
  if (parts.some(part => !part || ['__proto__', 'prototype', 'constructor'].includes(part))) throw Error('规则字段路径无效。')
  const settings = settingsObject(text)
  let value: unknown = raw.trim()
  const alternatives = Array.isArray(field.value_schema?.anyOf) ? field.value_schema.anyOf as Record<string, unknown>[] : []
  const constant = alternatives.find(schema => 'const' in schema && String(schema.const) === value)
  if (!value) value = undefined
  else if (constant) value = constant.const
  else if (field.type === 'number') {
    value = Number(value)
    if (typeof value !== 'number' || !Number.isFinite(value)) throw Error(`${field.label}必须填写有效数字。`)
    if (field.integer && !Number.isInteger(value)) throw Error(`${field.label}必须填写整数。`)
    if (field.exclusiveMinimum !== undefined && value <= field.exclusiveMinimum) throw Error(`${field.label}必须大于 ${field.exclusiveMinimum}。`)
    if ((field.minimum !== undefined && value < field.minimum) || (field.maximum !== undefined && value > field.maximum)) throw Error(`${field.label}超出允许范围。`)
  } else if (field.type === 'boolean') {
    if (value !== 'true' && value !== 'false') throw Error(`${field.label}请选择启用或关闭。`)
    value = value === 'true'
  } else if (field.type === 'lines') {
    const lines = raw.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
    const schema = field.value_schema?.items as Record<string, unknown> | undefined
    value = schema?.type === 'integer' ? lines.map(line => {
      const number = Number(line)
      if (!Number.isSafeInteger(number) || typeof schema.minimum === 'number' && number < schema.minimum || typeof schema.maximum === 'number' && number > schema.maximum) throw Error(`${field.label}必须填写有效的整数编号。`)
      return number
    }) : lines
  }
  else if (field.type === 'select' && !field.options?.some(option => option.value === value)) throw Error(`${field.label}请选择有效选项。`)
  const write = (target: Record<string, unknown>, index: number) => {
    const key = parts[index]
    if (index === parts.length - 1) { if (value === undefined) delete target[key]; else target[key] = value; return }
    const current = target[key]
    if (current !== undefined && (!current || typeof current !== 'object' || Array.isArray(current))) throw Error(`${parts.slice(0, index + 1).join('.')} 必须为对象，请先修正高级参数。`)
    const nested = { ...current as Record<string, unknown> | undefined }
    write(nested, index + 1)
    if (Object.keys(nested).length) target[key] = nested
    else delete target[key]
  }
  write(settings, 0)
  return JSON.stringify(settings, null, 2)
}

function flattened(value: unknown, prefix = ''): Map<string, string> {
  if (value && typeof value === 'object' && !Array.isArray(value)) return new Map(Object.entries(value)
    .sort(([left], [right]) => left.localeCompare(right)).flatMap(([key, nested]) => [...flattened(nested, prefix ? `${prefix}.${key}` : key)]))
  return new Map([[prefix, JSON.stringify(value) ?? '未设置']])
}

export function profileChanges(source: Profile, settings: Record<string, unknown>, plugins: string[]) {
  const previous = flattened(source.settings || {}), next = flattened(settings)
  const changes = [...new Set([...previous.keys(), ...next.keys()])].filter(path => previous.get(path) !== next.get(path))
    .map(path => ({ path, previous: previous.get(path) ?? '未设置', next: next.get(path) ?? '未设置' }))
  if (JSON.stringify(source.plugins || []) !== JSON.stringify(plugins)) changes.unshift({ path: 'plugins', previous: JSON.stringify(source.plugins || []), next: JSON.stringify(plugins) })
  return changes
}

export function parseImportedProfile(text: string): Profile {
  const value = settingsObject(text)
  if (typeof value.id !== 'string' || !/^[a-z][a-z0-9-]{0,63}$/.test(value.id) || typeof value.name !== 'string' || !value.name.trim()) throw Error('请选择包含有效 id、name、plugins 和 settings 的规则方案 JSON。')
  if (!Array.isArray(value.plugins) || !value.plugins.every(id => typeof id === 'string') || !value.plugins.length) throw Error('方案 plugins 必须为非空插件数组。')
  if (value.settings !== undefined && (!value.settings || typeof value.settings !== 'object' || Array.isArray(value.settings))) throw Error('方案 settings 必须为对象。')
  if (value.kinds !== undefined && (!Array.isArray(value.kinds) || !value.kinds.length || !value.kinds.every(kind => ['thesis', 'intern', 'certificate'].includes(String(kind))))) throw Error('方案的适用材料类型无效。')
  return value as unknown as Profile
}
