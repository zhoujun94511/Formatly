import { computed, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import type { DocumentKind, Requirement, School } from '../types'
import { requirementComparisonValue, requirementValue, type SchoolTargetField } from '../utils/profileFields'
import { clearGlobalSectionBinding } from '../utils/requirementScope'

export type RequirementDraft = Omit<Requirement, 'expected'> & { valueText: string }
export type SchoolDraftSnapshot = {
  drafts: RequirementDraft[]
  baseline: Map<string, string>
  version?: number
  conflicts: string[]
  savedFingerprint?: string
  saved?: boolean
}
export type SchoolDraftCache = Map<string, SchoolDraftSnapshot>

export function draftMatchesConflict(kind: string, target: string, conflicts: string[]) {
  if (conflicts.includes(`${kind}: ${target}`)) return true
  return (target === 'body.line_spacing' || target === 'paragraph.line_spacing_pt')
    && conflicts.includes(`${kind}: body.line_spacing / paragraph.line_spacing_pt`)
}
export interface SavedRequirementDraft {
  base_school_version: number
  baseline: RequirementDraft[]
  requirements: RequirementDraft[]
  refresh_conflicts: string[]
  updated_at?: string
}

let nextRequirement = 0
function requirementId(): string {
  // These identifiers name draft clauses; they are not authentication tokens.
  const sequence = (++nextRequirement).toString(36)
  const prefix = `user-${Date.now().toString(36)}-${sequence}-`
  const random = new Uint8Array(16)
  try {
    globalThis.crypto.getRandomValues(random)
    return prefix + Array.from(random, value => value.toString(16).padStart(2, '0')).join('')
  } catch {
    return prefix + Math.random().toString(36).slice(2)
  }
}

function expected(item: RequirementDraft, fields: SchoolTargetField[] = []): unknown {
  if (item.excluded || item.mode === 'manual') {
    const text = item.valueText.trim()
    if (item.target.startsWith('field.') && (!text || text === 'null')) return null
    return item.valueText
  }
  const metadata = fields.find(field => field.target === item.target)
  if (metadata) return requirementValue(item.valueText, metadata)
  if (/^page\.|^body\.(size_pt|line_spacing)$|^references\.(heading_after_lines|entry_hanging_chars)$|^paragraph\.(first_line_indent_chars|before_lines|after_lines|line_spacing_pt)$|^headings\.[1-9]\.(size_pt|before_lines|after_lines)$|^section\.(gutter_mm|header_distance_mm|footer_distance_mm|columns)$/.test(item.target)) {
    const value = Number(item.valueText)
    if (!item.valueText.trim() || !Number.isFinite(value)) throw Error(`${item.label || item.target} 必须填写有效数字。`)
    if ((['page.width_mm', 'page.height_mm', 'body.size_pt', 'body.line_spacing', 'paragraph.line_spacing_pt'].includes(item.target) || /^headings\.[1-9]\.size_pt$/.test(item.target)) && value <= 0) throw Error(`${item.label || item.target} 必须大于 0。`)
    if (item.target === 'section.columns' && !Number.isInteger(value)) throw Error(`${item.label || item.target} 必须填写整数。`)
    return value
  }
  if (item.target === 'body.style_ids') {
    let value: unknown
    try { value = JSON.parse(item.valueText) } catch { throw Error('正文样式 ID 应为非空字符串组成的 JSON 数组。') }
    if (!Array.isArray(value) || !value.length || value.some(part => typeof part !== 'string' || !part.trim())) throw Error('正文样式 ID 应为非空字符串组成的 JSON 数组。')
    return [...new Set((value as string[]).map(part => part.trim()))].sort()
  }
  if (item.target === 'references.citation_unique') {
    const value = item.valueText.trim().toLowerCase()
    if (value !== 'true' && value !== 'false') throw Error('参考文献重复引用规则必须填写 true 或 false。')
    return value === 'true'
  }
  if (item.target.startsWith('field.') && (!item.valueText.trim() || item.valueText.trim() === 'null')) return null
  return item.valueText
}

export function useRequirementEditor(cache: SchoolDraftCache = new Map(), fields: Readonly<Ref<SchoolTargetField[]>> = ref([])) {
  const drafts = ref<RequirementDraft[]>([]), acknowledged = ref(false), formError = ref('')
  const refreshConflicts = ref<string[]>([]), schoolVersion = ref<number>()
  const persistedIds = ref(new Set<string>())
  const schoolId = ref(''), baseline = ref(new Map<string, string>())
  const savedFingerprint = ref('')
  let latest: RequirementDraft[] = []
  let sourceKinds = new Map<string, DocumentKind>()
  const snapshot = (item: RequirementDraft) => JSON.stringify(item)
  const clone = (item: RequirementDraft): RequirementDraft => JSON.parse(JSON.stringify(item))
  const dirty = computed(() => !!schoolId.value && (drafts.value.length !== baseline.value.size
    || drafts.value.some(item => snapshot(item) !== baseline.value.get(item.id))))
  function cacheDraft() {
    if (!schoolId.value) return
    if (dirty.value || refreshConflicts.value.length) {
      cache.set(schoolId.value, { drafts: drafts.value.map(clone), baseline: new Map(baseline.value),
        version: schoolVersion.value, conflicts: [...refreshConflicts.value], savedFingerprint: savedFingerprint.value,
        saved: !!schoolVersion.value && JSON.stringify(exportDraft()) === savedFingerprint.value })
    } else cache.delete(schoolId.value)
  }
  function loadSchool(school: School, accept = false) {
    const valueText = (value: unknown) => value == null ? '' : typeof value === 'string' ? value : JSON.stringify(value, null, 2) ?? ''
    const incoming = [...new Map([...(school.candidates || []), ...(school.requirements || [])]
      .map(item => [item.id, { ...item, valueText: valueText(item.expected) }])).values()]
      .map(({ expected: _value, ...item }) => clone(item))
    latest = incoming
    sourceKinds = new Map(school.sources.map(source => [source.id, source.kind]))
    if (schoolId.value !== school.id) {
      cacheDraft()
      const saved = accept ? undefined : cache.get(school.id)
      schoolId.value = school.id
      drafts.value = saved?.drafts.map(clone) ?? incoming.map(clone)
      baseline.value = saved ? new Map(saved.baseline) : new Map(incoming.map(item => [item.id, snapshot(item)]))
      schoolVersion.value = saved?.version
      refreshConflicts.value = saved ? [...saved.conflicts] : []
      savedFingerprint.value = saved?.savedFingerprint || ''
    }
    if (accept) {
      drafts.value = incoming.map(clone); refreshConflicts.value = []
    } else {
      const local = new Map(drafts.value.map(item => [item.id, item]))
      const pending = new Set(refreshConflicts.value), merged: RequirementDraft[] = []
      for (const item of incoming) {
        const edit = local.get(item.id), previous = baseline.value.get(item.id)
        if (!edit || snapshot(edit) === previous || snapshot(edit) === snapshot(item)) {
          merged.push(clone(item)); pending.delete(item.id)
        } else {
          merged.push(edit)
          if (snapshot(item) !== previous) pending.add(item.id)
        }
        local.delete(item.id)
      }
      for (const item of local.values()) {
        if (!baseline.value.has(item.id)) merged.push(item)
        else if (snapshot(item) !== baseline.value.get(item.id)) { merged.push(item); pending.add(item.id) }
        else pending.delete(item.id)
      }
      drafts.value = merged; refreshConflicts.value = [...pending]
    }
    schoolVersion.value = school.version
    baseline.value = new Map(incoming.map(item => [item.id, snapshot(item)]))
    persistedIds.value = new Set(incoming.map(item => item.id))
    acknowledged.value = false; formError.value = ''
    cacheDraft()
  }
  function acceptLatest() { drafts.value = latest.map(clone); refreshConflicts.value = []; acknowledged.value = false; formError.value = ''; cacheDraft() }
  function keepLocalChanges() { refreshConflicts.value = []; acknowledged.value = false; formError.value = ''; cacheDraft() }
  function exportDraft(): SavedRequirementDraft {
    if (!schoolId.value || !schoolVersion.value) throw Error('请先读取学校要求。')
    return { base_school_version: schoolVersion.value, baseline: [...baseline.value.values()].map(value => JSON.parse(value)),
      requirements: drafts.value.map(clone), refresh_conflicts: [...refreshConflicts.value] }
  }
  function restoreDraft(school: School, saved: SavedRequirementDraft) {
    cache.set(school.id, { drafts: saved.requirements.map(clone), baseline: new Map(saved.baseline.map(item => [item.id, snapshot(item)])),
      version: saved.base_school_version, conflicts: [...saved.refresh_conflicts] })
    // Reload through the same three-way merge even when this school is open.
    schoolId.value = ''
    loadSchool(school)
    markDraftSaved(saved)
  }
  function markDraftSaved(saved: SavedRequirementDraft) { savedFingerprint.value = JSON.stringify({ base_school_version: saved.base_school_version,
    baseline: saved.baseline, requirements: saved.requirements, refresh_conflicts: saved.refresh_conflicts }); cacheDraft() }
  function canRemove(item: RequirementDraft) { return item.id.startsWith('user-') && !persistedIds.value.has(item.id) }
  function removeRequirement(item: RequirementDraft) {
    if (!canRemove(item)) { formError.value = '已保存要求请保留待确认，或填写理由后排除。'; return }
    drafts.value = drafts.value.filter(value => value.id !== item.id)
  }
  const confirmedCount = computed(() => drafts.value.filter(item => item.confirmed).length)
  const review = computed(() => {
    const stable = (value: unknown): unknown => Array.isArray(value) ? value.map(stable) : value && typeof value === 'object'
      ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, part]) => [key, stable(part)])) : value
    const groups = new Map<string, { item: RequirementDraft; value: string }[]>()
    const errors: string[] = []
    for (const [index, item] of drafts.value.entries()) {
      if (!item.confirmed || item.excluded || item.mode !== 'automatic') continue
      try {
        const value = expected(item, fields.value)
        if (item.target === 'required_heading') continue
        if (value === false && item.target.startsWith('structure.')) continue
        const key = `${item.kind}: ${item.target}`
        if (!groups.has(key)) groups.set(key, [])
        const parameters = Object.fromEntries(Object.entries(item.parameters || {}).filter(([name]) => !['style_ids', 'section_indices'].includes(name)))
        const comparable = requirementComparisonValue(value, fields.value.find(field => field.target === item.target))
        const entry = { item, value: JSON.stringify(stable([comparable, parameters])) }
        groups.get(key)!.push(entry)
        if (item.target === 'body.line_spacing' || item.target === 'paragraph.line_spacing_pt') {
          const cross = `${item.kind}: body.line_spacing / paragraph.line_spacing_pt`
          if (!groups.has(cross)) groups.set(cross, [])
          groups.get(cross)!.push(entry)
        }
      } catch (value) {
        errors.push(`第 ${index + 1} 条要求：${value instanceof Error ? value.message : String(value)}`)
      }
    }
    const disjoint = (left: RequirementDraft, right: RequirementDraft) => {
      const scope = fields.value.find(field => field.target === left.target)?.scope
      if (scope === 'global') return false
      const styles = (item: RequirementDraft) => item.scope_style_ids?.length ? item.scope_style_ids : Array.isArray(item.parameters?.style_ids) ? item.parameters.style_ids : []
      const sections = (item: RequirementDraft) => item.scope_section_indices?.length ? item.scope_section_indices : Array.isArray(item.parameters?.section_indices) ? item.parameters.section_indices : []
      const a = styles(left), b = styles(right), x = sections(left), y = sections(right)
      return !!(scope !== 'sections' && a.length && b.length && !a.some(value => b.includes(value)) || scope !== 'styles' && x.length && y.length && !x.some(value => y.includes(value)))
    }
    return { conflicts: [...groups].filter(([key, entries]) => entries.some((left, index) => entries.slice(index + 1).some(right => {
      const cross = key.endsWith('body.line_spacing / paragraph.line_spacing_pt')
      const different = cross ? left.item.target !== right.item.target : left.value !== right.value
      return different && !disjoint(left.item, right.item)
    }))).map(([key]) => key), errors }
  })
  const conflicts = computed(() => review.value.conflicts), inputErrors = computed(() => review.value.errors)
  watch(drafts, () => { acknowledged.value = false; formError.value = ''; cacheDraft() }, { deep: true })
  function beforeUnload(event: BeforeUnloadEvent) {
    cacheDraft()
    if (![...cache.values()].some(item => !item.saved)) return
    event.preventDefault()
    event.returnValue = ''
  }
  onMounted(() => { if (typeof window !== 'undefined') window.addEventListener('beforeunload', beforeUnload) })
  onUnmounted(() => {
    cacheDraft()
    if (typeof window !== 'undefined') window.removeEventListener('beforeunload', beforeUnload)
  })

  function addRequirement(kind: DocumentKind, sourceId = '') {
    drafts.value.push({ id: requirementId(), kind, target: 'manual.review', valueText: '', label: '', source_id: sourceId, source_locator: '', source_excerpt: '', mode: 'manual', confirmed: false })
    acknowledged.value = false
  }
  function clearSchool() {
    cacheDraft()
    schoolId.value = ''; drafts.value = []; baseline.value = new Map(); latest = []; sourceKinds = new Map()
    schoolVersion.value = undefined; persistedIds.value = new Set(); refreshConflicts.value = []
    savedFingerprint.value = ''; acknowledged.value = false; formError.value = ''
  }
  function prepare(): Requirement[] | null {
    formError.value = ''
    try {
      if (refreshConflicts.value.length) throw Error('要求已在其他窗口更新，请先处理版本冲突。')
      if (!acknowledged.value || !confirmedCount.value) throw Error('请逐条确认要求，并勾选下方核对声明。')
      if (inputErrors.value.length) throw Error(inputErrors.value[0])
      if (conflicts.value.length) throw Error('已确认的自动要求存在冲突。请选择一个自动值，其余改为人工复核或取消确认。')
      return drafts.value.flatMap((draft, index) => {
        if (canRemove(draft) && !draft.confirmed && !draft.excluded && !draft.label.trim()
          && !draft.valueText.trim() && !draft.source_locator.trim() && !draft.source_excerpt.trim()) return []
        const { valueText: _text, ...item } = draft
        clearGlobalSectionBinding(item)
        if (!item.label.trim() || !item.source_id) throw Error(`第 ${index + 1} 条要求需要名称和依据文件。`)
        if (schoolId.value && sourceKinds.get(item.source_id) !== item.kind) throw Error(`第 ${index + 1} 条要求须关联同类材料的依据文件。`)
        if (item.confirmed && !item.source_locator.trim()) throw Error(`第 ${index + 1} 条已确认要求需要出处定位。`)
        if (item.excluded && (!item.confirmed || !item.exclusion_reason?.trim())) throw Error(`第 ${index + 1} 条排除项须勾选确认，并填写明确的排除理由。`)
        let value: unknown
        try { value = expected(drafts.value[index], fields.value) } catch (error) {
          if (item.confirmed) throw error
          value = drafts.value[index].valueText
        }
        return [{ ...item, expected: value }]
      })
    } catch (value) {
      formError.value = value instanceof Error ? value.message : String(value)
      return null
    }
  }
  return { drafts, dirty, acknowledged, formError, confirmedCount, conflicts, inputErrors, refreshConflicts, schoolVersion,
    addRequirement, clearSchool, prepare, loadSchool, acceptLatest, keepLocalChanges, canRemove, removeRequirement, exportDraft, restoreDraft, markDraftSaved }
}
