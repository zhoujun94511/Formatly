<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { DocumentKind, Profile, SchoolSource } from '../types'
import { useSchoolWorkspace } from '../composables/useSchoolWorkspace'
import { draftMatchesConflict, useRequirementEditor, type SchoolDraftCache } from '../composables/useRequirementEditor'
import { useSchoolDraftPersistence } from '../composables/useSchoolDraftPersistence'
import { automaticTargets, automaticTargetGroups, documentKinds, kindLabel, profileLabel, requiresStyleScope } from '../utils/materials'
import { resolveSchoolProfiles } from '../utils/schoolProfiles'
import { updateRequirementSections } from '../utils/requirementScope'
import { displayEvidence } from '../utils/report'
import { useSchoolSourceText } from '../composables/useSchoolSourceText'
import { usePagedItems } from '../composables/usePagedItems'
import { useProfileFields } from '../composables/useProfileFields'
import ListPagination from '../components/ListPagination.vue'
import UploadDropzone from '../components/UploadDropzone.vue'
import DocumentCapabilities from '../components/DocumentCapabilities.vue'
import DocumentExtraction from '../components/DocumentExtraction.vue'
import WorkspaceWarnings from '../components/WorkspaceWarnings.vue'
import AppIcon from '../components/AppIcon.vue'
import SchoolStylePicker from '../components/SchoolStylePicker.vue'
import SchoolSourceContext from '../components/SchoolSourceContext.vue'
import RequirementValueInput from '../components/RequirementValueInput.vue'
import RuleFields from '../components/RuleFields.vue'
import SectionScopeInput from '../components/SectionScopeInput.vue'
import type { RequirementDraft } from '../composables/useRequirementEditor'

const props = defineProps<{ selectedId?: string; createNew?: boolean; profiles: Profile[]; refreshToken?: number; draftCache?: SchoolDraftCache }>()
const emit = defineEmits<{ select: [string]; confirmed: [Profile[]]; useProfile: [Profile]; navigate: [string] }>()
const workspace = useSchoolWorkspace()
const { items, selected, schoolWarnings, generatedProfiles, loading, saving, error, notice } = workspace
const name = ref(''), file = ref<File | null>(null), sourceKind = ref<DocumentKind>('thesis')
const sourceRole = ref('template')
const recoverySource = ref<SchoolSource | null>(null)
const { transcription, sourceIsPdf, transcriptionError } = useSchoolSourceText(file)
const generatedSection = ref<HTMLElement>()
const uploadSection = ref<HTMLElement>(), requirementSection = ref<HTMLElement>()
const expandedRequirementId = ref<string | null>(null)
const requirementNameInputs = new Map<string, HTMLInputElement>()
const confirmationError = ref(''), confirmationErrorElement = ref<HTMLElement>(), refreshConflictNotice = ref<HTMLElement>()
const currentProfiles = computed(() => resolveSchoolProfiles(selected.value, [...props.profiles, ...generatedProfiles.value]))
const nextActionLabel = computed(() => currentProfiles.value.length > 1 ? '选择方案检测' : currentProfiles.value.length ? '检测原稿' : selected.value?.sources.length ? '核对提取出的要求' : '返回新建检测')
const ruleMetadata = useProfileFields()
const schoolTargets = computed(() => ruleMetadata.metadata.value?.school_targets || [])
const targetMetadata = (target: string) => schoolTargets.value.find(field => field.target === target)
const targetGroups = computed(() => {
  const known = new Set(automaticTargets.map(([target]) => target))
  const additional = schoolTargets.value.filter(item => !known.has(item.target)).map(item => [item.target, item.label] as [string, string])
  return [...automaticTargetGroups, ...(additional.length ? [{ label: '文档结构', targets: additional }] : [])]
})
const availableTargets = computed(() => targetGroups.value.flatMap(group => group.targets))
const editor = useRequirementEditor(props.draftCache, schoolTargets)
const { drafts, dirty, acknowledged, formError, confirmedCount, conflicts, inputErrors, refreshConflicts } = editor
function changeTarget(item: RequirementDraft, event: Event) {
  item.target = (event.target as HTMLSelectElement).value
  item.parameters = undefined; item.scope_style_ids = undefined; item.scope_section_indices = undefined
  delete item.scope_binding_status; delete item.source_scope_style_ids; delete item.source_scope_section_indices; delete item.source_parameters
  item.confirmed = false; delete fieldModes.value[item.id]
}
function scopeType(item: RequirementDraft) { return targetMetadata(item.target)?.scope || (requiresStyleScope(item.target) ? 'styles' : 'global') }
function scopeSummary(item: RequirementDraft) {
  const parts: string[] = []
  if (styleScope(item).length) parts.push(`样式：${styleScope(item).join('、')}`)
  if (sectionScope(item).length) parts.push(`第 ${sectionScope(item).join('、')} 节`)
  return parts.join(' · ') || (scopeType(item) === 'global' || targetMetadata(item.target)?.allow_global_scope ? '全文要求' : '范围待核对')
}
function updateParameters(item: RequirementDraft, text: string) { item.parameters = JSON.parse(text) as Record<string, unknown> }
const parameterFields = (target: string) => targetMetadata(target)?.parameter_fields.filter(field => !['style_ids', 'section_indices'].includes(field.path)) || []
function styleScope(item: RequirementDraft): string[] { return item.scope_style_ids || (Array.isArray(item.parameters?.style_ids) ? item.parameters.style_ids.filter((value): value is string => typeof value === 'string') : []) }
function sectionScope(item: RequirementDraft): number[] { return item.scope_section_indices || (Array.isArray(item.parameters?.section_indices) ? item.parameters.section_indices.filter((value): value is number => typeof value === 'number') : []) }
function updateStyles(item: RequirementDraft, value: string[]) { item.scope_style_ids = value; if (item.parameters?.style_ids) item.parameters.style_ids = value }
function updateSections(item: RequirementDraft, value: number[]) { updateRequirementSections(item, value) }
const persistence = useSchoolDraftPersistence(selected, editor)
const filterKind = ref(''), filterStatus = ref('')
const confirming = ref(false)
const fieldModes = ref<Record<string, string>>({})
const fieldValueErrors = computed(() => drafts.value.flatMap((item, index) => item.confirmed && !item.excluded && item.mode === 'automatic'
  && item.target.startsWith('field.') && fieldModes.value[item.id] === 'fixed' && (!item.valueText.trim() || item.valueText.trim() === 'null')
  ? [`第 ${index + 1} 条要求：请选择“必须填写”，或填写明确的指定值。`] : []))
const draftLocked = computed(() => persistence.loading.value || !!persistence.pendingDraft.value)
const conflictingIds = computed(() => {
  const ids = new Set(refreshConflicts.value)
  for (const value of selected.value?.conflicts || []) {
    if (value && typeof value === 'object' && 'requirements' in value && Array.isArray(value.requirements)) {
      for (const id of value.requirements) if (typeof id === 'string') ids.add(id)
    }
  }
  for (const item of drafts.value) if (draftMatchesConflict(item.kind, item.target, conflicts.value)) ids.add(item.id)
  return ids
})
const visibleDrafts = computed(() => drafts.value.map((item, index) => ({ item, index })).filter(({ item }) => {
  if (filterKind.value && item.kind !== filterKind.value) return false
  if (filterStatus.value === 'pending') return !item.confirmed
  if (filterStatus.value === 'conflict') return conflictingIds.value.has(item.id)
  if (filterStatus.value === 'automatic' || filterStatus.value === 'manual') return item.mode === filterStatus.value
  if (filterStatus.value === 'excluded') return !!item.excluded
  return true
}))
const { page: requirementPage, displayed: pagedDrafts, setPage: setRequirementPage } = usePagedItems(visibleDrafts, 10, false)
const openRequirementId = computed(() => expandedRequirementId.value ?? (pagedDrafts.value[0]?.item.target === 'manual.source_clause' ? '' : pagedDrafts.value[0]?.item.id) ?? '')
const activeRequirement = computed(() => drafts.value.find(item => item.id === openRequirementId.value) || null)
const sourceContextPanel = ref<InstanceType<typeof SchoolSourceContext>>()
function toggleRequirement(id: string) { expandedRequirementId.value = openRequirementId.value === id ? '' : id }
function retainRequirementInput(id: string, input: unknown) {
  if (input) requirementNameInputs.set(id, input as HTMLInputElement)
  else requirementNameInputs.delete(id)
}
const schoolSources = computed(() => selected.value?.sources || [])
const attentionSources = computed(() => schoolSources.value.filter(source => source.extraction?.complete === false
  || ['partial', 'needs_transcription', 'failed', 'error'].includes(source.parse_status || source.extraction_status || '')))
const hasAutomaticCandidates = computed(() => drafts.value.some(item => item.mode === 'automatic'))
const publicationScope = computed(() => {
  const scope = { automatic: 0, manual: 0, pending: 0, excluded: 0 }
  const explicitStyles = new Set(drafts.value.filter(item => item.confirmed && !item.excluded && item.mode === 'automatic' && item.target === 'body.style_ids').flatMap(item => {
    try { const value: unknown = JSON.parse(item.valueText); return Array.isArray(value) && value.some(part => typeof part === 'string' && part.trim()) ? [item.kind] : [] } catch { return [] }
  }))
  for (const item of drafts.value) {
    if (!item.confirmed) scope.pending++
    else if (item.excluded) scope.excluded++
    else if (item.mode === 'manual' || scopeType(item) === 'styles' && !styleScope(item).length && !explicitStyles.has(item.kind)
      || scopeType(item) === 'sections' && !sectionScope(item).length && !targetMetadata(item.target)?.allow_global_scope || targetMetadata(item.target)?.type === 'boolean' && item.valueText.trim() === 'false') scope.manual++
    else scope.automatic++
  }
  return scope
})
const { page: sourcePage, displayed: pagedSources, setPage: setSourcePage } = usePagedItems(schoolSources, 10, false)
watch([filterKind, filterStatus, () => selected.value?.id], () => setRequirementPage(1), { flush: 'sync' })
watch([requirementPage, filterKind, filterStatus, () => selected.value?.id], () => { expandedRequirementId.value = null }, { flush: 'sync' })
watch(() => selected.value?.id, () => setSourcePage(1), { flush: 'sync' })
function goToSection(section?: HTMLElement) {
  section?.focus({ preventScroll: true })
  section?.scrollIntoView({ block: 'start', behavior: 'auto' })
}
watch(() => selected.value && !currentProfiles.value.length && selected.value.sources.length ? selected.value.id : '', async id => {
  if (!id) return
  await nextTick()
  goToSection(requirementSection.value)
})
function continueToAudit() {
  if (selected.value?.sources.length && !currentProfiles.value.length) { goToSection(requirementSection.value); return }
  if (!currentProfiles.value.length) emit('navigate', 'new')
  else if (!saving.value && !dirty.value) {
    if (currentProfiles.value.length === 1) emit('useProfile', currentProfiles.value[0])
    else goToSection(generatedSection.value)
  }
}
function recoverSource(source: SchoolSource) {
  recoverySource.value = source; file.value = null; sourceKind.value = source.kind; sourceRole.value = source.role
  void nextTick(() => goToSection(uploadSection.value))
}
const extractionStatusLabels: Record<string, string> = {
  extracted: '已提取文本', ocr: '已识别，需核对', partial: '提取未完成', transcribed: '已采用核对文本',
  needs_transcription: '待补充核对文本', failed: '提取失败', error: '提取失败', pending: '等待提取',
}
const extractionStatusLabel = (status?: string) => extractionStatusLabels[status || ''] || (status ? '状态需核对' : '未记录')
function conflictLabel(key: string) {
  const separator = key.indexOf(': '), kind = key.slice(0, separator), target = key.slice(separator + 2)
  const label = availableTargets.value.find(([value]) => value === target)?.[1] || '格式要求'
  return separator >= 0 ? `${kindLabel(kind)} · ${label}` : '格式要求'
}
const confirmError = computed(() => confirmationError.value || formError.value)
watch(drafts, () => { confirmationError.value = '' }, { deep: true })
let draftSchoolId = ''
watch(selected, school => {
  if (!school) { editor.clearSchool(); fieldModes.value = {}; return }
  if (draftSchoolId && draftSchoolId !== school.id) { file.value = null; transcription.value = '' }
  const kinds = [...new Set(school.sources.map(source => source.kind))]
  if (kinds.length === 1 || kinds.length && !kinds.includes(sourceKind.value)) sourceKind.value = kinds[0]
  editor.loadSchool(school); draftSchoolId = school.id
})
watch([() => props.selectedId, () => props.createNew], ([id, createNew]) => {
  if (createNew) { file.value = null; transcription.value = ''; name.value = ''; draftSchoolId = ''; recoverySource.value = null }
  if (id && selected.value?.id === id) return
  void workspace.select(id || '')
}, { immediate: true })
watch(() => props.refreshToken, () => { void workspace.refresh(); if (props.selectedId && !saving.value) void workspace.select(props.selectedId) })
function nameForUpload() {
  const typed = name.value.trim()
  if (typed || selected.value) return typed
  const stem = file.value?.name.replace(/\.[^.]+$/, '').trim() || '学校要求'
  return stem.slice(0, 120)
}
async function upload() {
  if (!file.value || saving.value || transcriptionError.value) return
  const body = new FormData()
  body.append('source', file.value); body.append('kind', sourceKind.value); body.append('role', sourceRole.value)
  if (sourceIsPdf.value && transcription.value.trim()) body.append('transcription', transcription.value)
  const uploaded = await workspace.addSource(body, nameForUpload())
  if (uploaded) { file.value = null; transcription.value = ''; name.value = ''; recoverySource.value = null }
  if (selected.value && selected.value.id !== props.selectedId) emit('select', selected.value.id)
  if (uploaded) { await nextTick(); goToSection(requirementSection.value) }
}
function addRequirement() {
  const kind = documentKinds.find(item => item.value === filterKind.value)?.value || sourceKind.value
  editor.addRequirement(kind, selected.value?.sources.find(source => source.kind === kind)?.id)
  filterKind.value = ''; filterStatus.value = ''
  setRequirementPage(Math.ceil(drafts.value.length / 10))
  expandedRequirementId.value = drafts.value.at(-1)?.id || ''
  void nextTick(() => {
    const input = requirementNameInputs.get(expandedRequirementId.value || '')
    input?.focus()
    input?.scrollIntoView({ block: 'nearest', behavior: 'auto' })
  })
}
async function confirm() {
  if (confirming.value || draftLocked.value) return
  confirmationError.value = ''
  if (fieldValueErrors.value.length) { confirmationError.value = fieldValueErrors.value[0]; return }
  const requirements = editor.prepare()
  if (!requirements) { await nextTick(); confirmationErrorElement.value?.focus(); return }
  confirming.value = true
  try {
    if (!await persistence.flush()) { confirmationError.value = persistence.error.value || '草稿尚未保存，请先重试保存或读取最新草稿。'; return }
    if (await workspace.confirm(requirements, editor.schoolVersion.value)) {
      if (selected.value) editor.loadSchool(selected.value, true)
      await persistence.discard(false)
      emit('confirmed', generatedProfiles.value)
      await nextTick()
      generatedSection.value?.focus()
      generatedSection.value?.scrollIntoView({ block: 'start', behavior: 'auto' })
    } else {
      confirmationError.value = error.value || '方案保存失败，请重试。'
    }
  } finally {
    confirming.value = false
    if (confirmationError.value) { await nextTick(); confirmationErrorElement.value?.focus() }
  }
}
async function readLatestRequirements() {
  const id = selected.value?.id || props.selectedId
  if (!id || saving.value) return
  await workspace.select(id)
  if (selected.value) await persistence.read()
  confirmationError.value = selected.value ? '' : error.value || '无法读取最新要求，请重试。'
  await nextTick()
  if (confirmationError.value) confirmationErrorElement.value?.focus()
  else refreshConflictNotice.value?.focus()
}
watch(() => props.createNew, creating => {
  if (!creating) return
  void nextTick(() => {
    const section = uploadSection.value
    if (typeof section?.querySelector === 'function') section.querySelector<HTMLElement>('.dropzone')?.focus({ preventScroll: true })
    section?.scrollIntoView({ block: 'start', behavior: 'auto' })
  })
}, { immediate: true })
onMounted(async () => { await workspace.refresh(); if (!props.createNew && !props.selectedId && items.value[0]) emit('select', items.value[0].id) })
</script>

<template>
  <div class="page materials-page schools-page">
    <div class="page-heading"><div><h1>学校要求</h1><p>{{ selected ? '核对要求并保存后，即可回来检测原稿。' : '先放入学校文件。上传之后再核对要求。' }}</p></div><button v-if="selected" class="button secondary" type="button" :disabled="saving || !!currentProfiles.length && dirty" @click="continueToAudit">{{ nextActionLabel }}<AppIcon name="arrow-right" /></button></div>
    <p v-if="error && !confirmationError" class="notice error-notice" role="alert">{{ error }}</p><p v-if="notice" class="notice neutral-notice" role="status">{{ notice }}</p>
    <WorkspaceWarnings :warnings="schoolWarnings" label="学校要求" />
    <section v-if="!createNew && items.length" class="panel workspace-picker school-picker">
      <div class="form-group"><label for="school-picker">已保存的学校要求</label><select id="school-picker" :value="selectedId || ''" :disabled="saving || loading" @change="emit('select', ($event.target as HTMLSelectElement).value)"><option value="" disabled>请选择已保存的要求</option><option v-for="item in items" :key="item.id" :value="item.id">{{ item.name }} · 第 {{ item.version || 1 }} 版</option></select></div>
      <button class="button secondary new-school-button" type="button" :disabled="saving" @click="emit('navigate', 'schools/new')"><AppIcon name="plus" />新建学校要求</button>
    </section>
    <p v-else-if="!selected && !loading" class="notice neutral-notice" role="status">下一步：放入学校模板或格式说明，再点击“上传并提取要求”。名称可以留空。<button class="text-button" type="button" @click="emit('navigate', 'new')">返回新建检测</button></p>
    <nav v-if="selected" class="school-steps" aria-label="学校要求处理步骤">
      <button type="button" @click="goToSection(uploadSection)"><span class="school-step-number" :class="{ complete: selected?.sources.length }">1</span><span><strong>上传模板与说明</strong><small>{{ selected?.sources.length ? `${selected.sources.length} 份来源文件` : '添加学校提供的文件' }}</small></span><AppIcon name="chevron-right" /></button>
      <button type="button" :disabled="!selected" @click="goToSection(requirementSection)"><span class="school-step-number" :class="{ complete: currentProfiles.length && !dirty }">2</span><span><strong>核对格式要求</strong><small>{{ drafts.length ? `已确认 ${confirmedCount} / ${drafts.length} 条` : '确认要求值与出处' }}</small></span><AppIcon name="chevron-right" /></button>
      <button type="button" :disabled="!selected" @click="goToSection(generatedSection)"><span class="school-step-number" :class="{ complete: currentProfiles.length && !dirty }">3</span><span><strong>保存方案并检测</strong><small>{{ currentProfiles.length && !dirty ? `${currentProfiles.length} 个可用方案` : '核对后生成检测方案' }}</small></span></button>
    </nav>
    <p v-if="loading && !selected" class="empty-state" role="status">正在读取学校依据…</p>
      <section v-if="selected || !loading" ref="uploadSection" class="panel materials-panel school-upload" tabindex="-1" aria-labelledby="school-upload-heading">
        <div class="panel-heading"><div><h2 id="school-upload-heading">上传模板与说明</h2><p v-if="selected" class="field-help">{{ selected.name }} · 第 {{ selected.version || 1 }} 版</p></div><span class="optional-label">第 1 步</span></div>
        <div v-if="attentionSources.length" class="notice warm-notice source-recovery" role="status"><p>{{ attentionSources.length }} 份来源提取未完成或需要补充，遗漏内容不会自动成为检测规则。</p><ul><li v-for="source in attentionSources.slice(0, 3)" :key="source.id"><strong>{{ source.filename }}</strong> · {{ extractionStatusLabel(source.parse_status || source.extraction_status) }}<span v-if="source.extraction?.processed_pages !== undefined && source.extraction?.page_count"> · 已处理 {{ source.extraction.processed_pages }} / {{ source.extraction.page_count }} 页</span><button class="text-button" type="button" :disabled="saving" @click="recoverSource(source)">重新选择文件并补文本</button></li></ul><p v-if="attentionSources.length > 3" class="field-help">其余来源状态见下方文件列表。</p><button class="text-button" type="button" :disabled="saving || draftLocked" @click="addRequirement">手动补充遗漏要求</button></div>
        <details class="school-add-source" :class="{ 'is-creating': !selected }" :open="!selected?.sources.length || !!file || !!recoverySource"><summary v-show="!!selected"><AppIcon name="plus" />添加模板或说明<AppIcon name="chevron-right" /></summary>
        <div v-if="recoverySource" class="notice neutral-notice" role="status"><p>请重新选择“{{ recoverySource.filename }}”，展开“校正识别文本”并粘贴核对后的要求，再上传。原来源不会在此被替换；请核对并处理重复候选。</p><button class="text-button" type="button" @click="recoverySource = null">取消补充</button></div>
        <form @submit.prevent="upload"><fieldset class="dialog-fields" :disabled="saving">
          <div v-if="!selected" class="form-group"><label for="school-name">学校要求名称 <span class="optional-label">可选</span></label><input id="school-name" v-model="name" maxlength="120" placeholder="留空则使用文件名" /><p class="field-help">留空时用文件名作为这组要求的名称。</p></div>
          <div class="form-grid"><div class="form-group"><label for="source-kind">适用材料</label><select id="source-kind" v-model="sourceKind"><option v-for="item in documentKinds" :key="item.value" :value="item.value">{{ item.label }}</option></select></div><div class="form-group"><label for="source-role">依据类型</label><select id="source-role" v-model="sourceRole"><option value="template">学校模板</option><option value="instructions">规范说明</option></select></div></div>
          <div class="form-group"><UploadDropzone v-model="file" label="学校模板或格式说明" :disabled="saving" /><p class="field-help">单件 ≤ 40 MB，可分次添加模板和说明。</p><p v-if="file" class="field-help">此文件尚未上传，刷新后需重新选择。</p></div>
          <DocumentCapabilities v-if="sourceIsPdf" />
          <details v-if="sourceIsPdf" class="form-group"><summary>校正识别文本（可选）</summary><label for="source-transcription">已核对的文本</label><textarea id="source-transcription" v-model="transcription" rows="4" :aria-invalid="!!transcriptionError" :aria-describedby="transcriptionError ? 'source-transcription-help source-transcription-error' : 'source-transcription-help'" placeholder="粘贴核对后的文本，保留页码或条款位置。" /><p id="source-transcription-help" class="field-help">填写后以此文本替代自动识别结果；不超过 1 MB（UTF-8）。</p></details>
          <p v-if="transcriptionError" id="source-transcription-error" class="notice error-notice" role="alert">{{ transcriptionError }}</p>
          <div class="school-upload-actions"><span class="field-help">{{ file ? '已选择文件，上传后提取要求' : '选择学校提供的模板或格式说明' }}</span><button class="button primary" type="submit" :disabled="!file || saving || !!transcriptionError"><AppIcon name="upload" />{{ saving ? '正在上传并提取…' : '上传并提取要求' }}</button></div>
        </fieldset></form></details>
        <template v-if="selected">
        <div v-if="schoolSources.length" class="school-sources-heading"><h3>已上传来源</h3><span>{{ schoolSources.length }} 份文件</span></div><div class="source-list"><details v-for="source in pagedSources" :key="source.id"><summary>{{ source.filename }} · {{ kindLabel(source.kind) }} · {{ source.role === 'template' ? '模板' : '说明' }}</summary><p class="field-help">提取状态：{{ extractionStatusLabel(source.parse_status || source.extraction_status) }}</p><DocumentExtraction v-if="source.extraction" :extraction="source.extraction" :method="source.text_method" /><p v-for="warning in source.warnings?.filter(value => !source.extraction?.warnings?.includes(value))" :key="warning" class="notice warm-notice">{{ warning }}</p><details><summary>文件校验信息</summary><p v-if="source.parse_status || source.extraction_status" class="issue-source">提取状态标识：{{ source.parse_status || source.extraction_status }}</p><p class="issue-source">原件 SHA256：{{ source.sha256 }}</p><p class="issue-source">有效文本 SHA256：{{ source.text_sha256 || '历史记录未保存' }}</p><p v-if="source.extracted_text_sha256" class="issue-source">自动提取文本 SHA256：{{ source.extracted_text_sha256 }}</p><p v-if="source.transcription_sha256" class="issue-source">人工核对文本 SHA256：{{ source.transcription_sha256 }}</p></details><pre class="evidence-block">{{ source.text || '未取得文本，请补充校正文本或手动添加要求。' }}</pre><a class="text-button" :href="`/api/schools/${encodeURIComponent(selected.id)}/sources/${encodeURIComponent(source.id)}`" download>下载原件</a></details></div><ListPagination :page="sourcePage" :total="schoolSources.length" label="学校来源文件分页" @change="setSourcePage" />
        </template>
      </section>
    <template v-if="selected">
      <section ref="requirementSection" class="panel materials-panel school-requirements" tabindex="-1" aria-labelledby="school-requirements-heading">
        <div class="panel-heading"><div><h2 id="school-requirements-heading">核对格式要求</h2><p class="field-help">逐条核对；签章、视觉效果等要求选择“人工复核”。</p></div><button class="button secondary" type="button" :disabled="saving || confirming || draftLocked || !selected.sources.length" @click="addRequirement">添加要求</button></div>
        <p v-if="ruleMetadata.error.value" class="notice warning-notice" role="alert">规则编辑选项读取失败，请重新读取后再编辑结构要求。<button class="text-button" type="button" @click="ruleMetadata.load">重新读取规则选项</button></p>
        <details v-if="selected.conflicts?.length" class="notice warm-notice"><summary>来源中存在候选值冲突</summary><pre class="evidence-block">{{ displayEvidence(selected.conflicts) }}</pre></details>
        <div v-if="refreshConflicts.length" ref="refreshConflictNotice" class="notice warm-notice" role="alert" tabindex="-1"><p>部分要求已在其他窗口更新。本地修改已保留，请核对后选择。</p><div class="dialog-actions"><button class="button secondary" type="button" :disabled="saving" @click="editor.acceptLatest">采用最新要求</button><button class="button secondary" type="button" :disabled="saving" @click="editor.keepLocalChanges">核对后保留本地修改</button></div></div>
        <div v-if="!hasAutomaticCandidates" class="notice neutral-notice"><p>尚未整理出可自动检查的要求。可对照原件补充纸张、字体、必填字段等规则，签字和盖章保留人工复核。</p><button class="button secondary" type="button" :disabled="saving || draftLocked" @click="addRequirement">手动补充要求</button></div>
        <div class="draft-toolbar" :aria-busy="persistence.loading.value || persistence.saving.value">
          <span class="field-help" role="status">{{ persistence.loading.value ? '正在读取草稿…' : persistence.saving.value ? '正在保存草稿…' : persistence.notice.value || (dirty ? '要求有修改，草稿自动保存；生成方案后才生效。' : '当前为已保存要求。') }}</span>
          <button v-if="dirty && !persistence.pendingDraft.value" class="text-button" type="button" :disabled="saving || persistence.saving.value || draftLocked || persistence.conflict.value" @click="persistence.save">保存草稿</button>
          <button v-if="persistence.hasSavedDraft.value && !persistence.pendingDraft.value" class="text-button" type="button" :disabled="saving || persistence.saving.value" @click="persistence.discard()">丢弃草稿并读取已保存要求</button>
        </div>
        <p v-if="persistence.error.value" class="notice error-notice" role="alert">{{ persistence.error.value }} <button class="text-button" type="button" :disabled="saving || persistence.loading.value || persistence.saving.value" @click="readLatestRequirements">读取最新要求与草稿</button></p>
        <div v-if="persistence.pendingDraft.value" class="notice warm-notice draft-recovery" role="status">
          <p>发现已保存草稿（学校要求第 {{ persistence.pendingDraft.value.base_school_version }} 版），请先选择恢复或丢弃。</p>
          <div class="draft-actions"><button class="button secondary" type="button" :disabled="saving || persistence.saving.value" @click="persistence.restore">恢复已保存草稿</button><button v-if="dirty" class="button secondary" type="button" :disabled="saving || persistence.saving.value" @click="persistence.keepLocal">保留当前编辑并保存</button><button class="text-button" type="button" :disabled="saving || persistence.saving.value" @click="persistence.discard()">丢弃草稿并读取已保存要求</button></div>
        </div>
        <div v-if="drafts.length" class="form-grid requirement-filters"><div class="form-group"><label for="requirement-filter-kind">材料类型</label><select id="requirement-filter-kind" v-model="filterKind"><option value="">全部材料</option><option v-for="kind in documentKinds" :key="kind.value" :value="kind.value">{{ kind.label }}</option></select></div><div class="form-group"><label for="requirement-filter-status">要求筛选</label><select id="requirement-filter-status" v-model="filterStatus"><option value="">全部要求</option><option value="pending">待确认</option><option value="conflict">有冲突</option><option value="automatic">自动检查</option><option value="manual">人工复核</option><option value="excluded">已排除</option></select></div></div>
        <p v-if="drafts.length" class="field-help" role="status">匹配 {{ visibleDrafts.length }} / {{ drafts.length }} 条要求；筛选与翻页不影响全量保存。</p>
        <p v-if="drafts.length && !visibleDrafts.length" class="empty-state">没有符合筛选的要求。</p>
        <ListPagination :page="requirementPage" :total="visibleDrafts.length" :disabled="saving || confirming || draftLocked" label="学校要求分页" @change="setRequirementPage" />
        <div class="requirement-workbench">
        <SchoolSourceContext ref="sourceContextPanel" :school="selected" :requirement="activeRequirement" />
        <div class="requirement-fields"><fieldset class="dialog-fields" :disabled="saving || confirming || draftLocked">
          <article v-for="({ item, index }) in pagedDrafts" :key="item.id" class="requirement-editor" :class="{ 'requirement-confirmed': item.confirmed, 'requirement-conflict': conflictingIds.has(item.id) }">
            <details class="requirement-disclosure" :open="item.id === openRequirementId">
              <summary :aria-expanded="item.id === openRequirementId" @click.prevent="toggleRequirement(item.id)"><span class="requirement-order">{{ index + 1 }}</span><span class="requirement-summary-text"><strong>{{ item.label || '未命名要求' }}</strong><small>{{ kindLabel(item.kind) }} · {{ item.mode === 'automatic' ? '自动检查' : '人工复核' }} · {{ scopeSummary(item) }}</small></span><span class="requirement-state" :class="{ conflict: conflictingIds.has(item.id) }">{{ conflictingIds.has(item.id) ? '有冲突' : item.excluded ? '已排除' : item.confirmed ? '已确认' : '待确认' }}</span><AppIcon name="chevron-right" /></summary>
              <div class="requirement-edit-body">
            <div class="requirement-heading"><label class="checkbox-row"><input v-model="item.confirmed" type="checkbox" @change="acknowledged = false" /><span>确认第 {{ index + 1 }} 条要求</span></label><button v-if="editor.canRemove(item)" class="text-button" type="button" @click="editor.removeRequirement(item)">移除新增项</button><button v-else class="text-button" type="button" :disabled="!item.confirmed" @click="item.confirmed = false">保留待确认</button></div>
            <button v-if="item.id === openRequirementId" class="text-button source-context-link" type="button" @click="sourceContextPanel?.show()">查看来源对照</button>
            <label class="checkbox-row"><input v-model="item.excluded" type="checkbox" /><span>不适用，排除检查<small v-if="item.excluded">请确认本条并填写理由。排除项不计为通过。</small></span></label>
            <div v-if="item.excluded" class="form-group"><label :for="`requirement-exclusion-${index}`">排除理由（必填）</label><textarea :id="`requirement-exclusion-${index}`" v-model="item.exclusion_reason" rows="2" maxlength="1000" required placeholder="填写不适用的原因" /></div>
            <div class="form-grid"><div class="form-group"><label :for="`requirement-label-${index}`">要求名称</label><input :id="`requirement-label-${index}`" :ref="element => retainRequirementInput(item.id, element)" v-model="item.label" maxlength="240" /></div><div class="form-group"><label :for="`requirement-kind-${index}`">适用材料</label><select :id="`requirement-kind-${index}`" v-model="item.kind"><option v-for="kind in documentKinds" :key="kind.value" :value="kind.value">{{ kind.label }}</option></select></div></div>
            <div class="form-grid"><div class="form-group"><label :for="`requirement-mode-${index}`">执行方式</label><select :id="`requirement-mode-${index}`" v-model="item.mode"><option value="automatic">自动检查</option><option value="manual">人工复核</option></select></div><div class="form-group"><label :for="`requirement-target-${index}`">检查目标</label><select v-if="item.mode === 'automatic'" :id="`requirement-target-${index}`" :value="item.target" @change="changeTarget(item, $event)"><option v-if="!availableTargets.some(([key]) => key === item.target)" :value="item.target">{{ item.target }}（请重新选择）</option><optgroup v-for="group in targetGroups" :key="group.label" :label="group.label"><option v-for="[target, label] in group.targets" :key="target" :value="target">{{ label }}</option></optgroup></select><input v-else :id="`requirement-target-${index}`" v-model="item.target" maxlength="120" /></div></div>
            <RequirementValueInput v-model="item.valueText" :target="item.target" :mode="item.mode" :metadata="targetMetadata(item.target)" :input-id="`requirement-value-${index}`" :field-mode="fieldModes[item.id]" @update:field-mode="fieldModes[item.id] = $event" />
            <SchoolStylePicker v-if="item.id === openRequirementId && item.mode === 'automatic' && scopeType(item) === 'styles'" :model-value="styleScope(item)" @update:model-value="updateStyles(item, $event)" :school="selected" :kind="item.kind" :source-id="item.source_id" :input-id="`requirement-scope-${index}`" />
            <SectionScopeInput v-if="item.mode === 'automatic' && scopeType(item) === 'sections'" :allow-global="targetMetadata(item.target)?.allow_global_scope" :model-value="sectionScope(item)" @update:model-value="updateSections(item, $event)" :input-id="`requirement-sections-${index}`" />
            <RuleFields v-if="item.mode === 'automatic' && parameterFields(item.target).length" :model-value="JSON.stringify(item.parameters || {})" :fields="parameterFields(item.target)" :id-prefix="`requirement-parameters-${index}`" @update:model-value="updateParameters(item, $event)" />
            <div class="form-grid"><div class="form-group"><label :for="`requirement-source-${index}`">依据文件</label><select :id="`requirement-source-${index}`" v-model="item.source_id"><option value="">请选择来源</option><option v-for="source in selected.sources.filter(value => value.kind === item.kind)" :key="source.id" :value="source.id">{{ source.filename }}</option></select></div><div class="form-group"><label :for="`requirement-locator-${index}`">出处定位</label><input :id="`requirement-locator-${index}`" v-model="item.source_locator" maxlength="300" placeholder="例如：第 3 页 2.1 条" /></div></div>
            <div class="form-group"><label :for="`requirement-excerpt-${index}`">原文摘录</label><textarea :id="`requirement-excerpt-${index}`" v-model="item.source_excerpt" rows="2" maxlength="2000" /></div>
              </div>
            </details>
          </article>
          <ListPagination :page="requirementPage" :total="visibleDrafts.length" :disabled="saving || confirming || draftLocked" label="学校要求底部分页" @change="setRequirementPage" />
          <p v-for="message in inputErrors" :key="message" class="notice error-notice" role="alert">{{ message }}</p>
          <p v-for="message in fieldValueErrors" :key="message" class="notice error-notice" role="alert">{{ message }}</p>
          <p v-for="key in conflicts" :key="key" class="notice error-notice" role="alert">已确认要求的适用范围交叠：{{ conflictLabel(key) }}。请核对范围与要求值；无法区分时改为人工复核或保留待确认。</p>
          <details v-if="conflicts.length" class="form-group"><summary>冲突技术标识</summary><p v-for="key in conflicts" :key="key" class="issue-source">{{ key }}</p></details>
          <div class="publication-scope" role="status" aria-label="方案生成范围"><strong>本次生成范围</strong><p>{{ publicationScope.automatic }} 条预计可检查 · {{ publicationScope.manual }} 条人工复核 · {{ publicationScope.pending }} 条待确认 · {{ publicationScope.excluded }} 条已排除</p><p v-if="publicationScope.pending" class="field-help">待确认要求不会自动执行，报告会保留其未确认状态。</p><p v-if="publicationScope.manual" class="field-help">尚未匹配原稿范围、关闭或需人工处理的要求不计为自动通过；实际能力以原稿预检为准。</p></div>
          <label class="checkbox-row"><input v-model="acknowledged" type="checkbox" /><span>已核对来源、材料类型和要求值；无法自动检查的内容已选人工复核。</span></label>
          <p class="field-help">全部要求已勾选 {{ confirmedCount }} / {{ drafts.length }} 条</p>
          <div v-if="confirmError" class="notice error-notice"><p ref="confirmationErrorElement" role="alert" tabindex="-1">{{ confirmError }}</p><button v-if="confirmationError" class="button secondary" type="button" :disabled="saving || loading" @click="readLatestRequirements">读取最新要求</button></div>
          <button class="button primary" type="button" :disabled="saving || confirming || draftLocked || !persistence.ready.value || persistence.conflict.value || !acknowledged || !confirmedCount || !!conflicts.length || !!inputErrors.length || !!fieldValueErrors.length || !!refreshConflicts.length" @click="confirm">{{ saving || confirming ? '正在生成方案…' : '确认并生成方案' }}</button>
        </fieldset></div>
        </div>
      </section>
      <section ref="generatedSection" class="panel materials-panel generated-profiles" tabindex="-1" aria-labelledby="generated-profiles-heading">
        <div class="panel-heading"><h2 id="generated-profiles-heading">保存方案并检测</h2><span class="optional-label">第 3 步</span></div>
        <p v-if="dirty && currentProfiles.length" class="notice warm-notice" role="status">要求有未保存修改，请先重新确认并生成方案。</p>
        <ul v-if="currentProfiles.length" class="school-profile-list">
          <li v-for="profile in currentProfiles" :key="profile.id">
            <div><strong>{{ profileLabel(profile) }}</strong><p class="field-help">{{ profile.kinds?.map(kindLabel).join(' / ') }}</p></div>
            <button class="button primary" type="button" :disabled="saving || dirty" @click="emit('useProfile', profile)">使用此方案检测</button>
          </li>
        </ul>
        <p v-else class="field-help">{{ selected.status === 'confirmed' ? '正在读取已保存方案；若未显示，请刷新页面。' : '确认格式要求并生成方案后，即可选择方案检测原稿。' }}</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.school-picker { grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 20px; padding: 14px 20px; margin-bottom: 20px; }
.school-picker > .form-group { margin-bottom: 0; }
.new-school-button { justify-self: stretch; }
.school-steps { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin-bottom: 24px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface); overflow: hidden; }
.school-steps > button { display: flex; align-items: center; text-align: left; gap: 12px; min-width: 0; min-height: 72px; padding: 12px 20px; color: var(--ink); border: 0; background: transparent; }
.school-steps > button + button { border-left: 1px solid var(--line); }
.school-steps > button:hover:not(:disabled) { background: var(--surface-hover); }
.school-steps > button > span:not(.school-step-number) { flex: 1; min-width: 0; }
.school-steps strong, .school-steps small { display: block; overflow-wrap: anywhere; }
.school-steps strong { font-size: 15px; line-height: 1.5; font-weight: 600; }
.school-steps small { margin-top: 3px; font-size: 13px; color: var(--muted); }
.school-steps :deep(svg) { width: 16px; height: 16px; flex: none; color: var(--subtle); }
.school-step-number { flex: none; display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid var(--line-strong); border-radius: 50%; background: var(--surface-soft); color: var(--muted); font-size: 13px; font-weight: 600; }
.school-step-number.complete { border-color: var(--success-line); color: var(--success); background: var(--success-bg); }
.materials-panel { padding: 24px; scroll-margin-top: 84px; }
.school-upload :deep(.dropzone) { min-height: 176px; }
.school-add-source > summary { display: flex; align-items: center; gap: 8px; min-height: 44px; padding-block: 10px; color: var(--brand); font-size: 15px; font-weight: 600; cursor: pointer; list-style: none; }
.school-add-source.is-creating > summary { display: none; }
.school-add-source > summary::-webkit-details-marker { display: none; }
.school-add-source > summary :deep(svg) { width: 17px; height: 17px; flex: none; }
.school-add-source > summary > :deep(svg:last-child) { margin-left: auto; }
.school-add-source[open] > summary > :deep(svg:last-child) { transform: rotate(90deg); }
.school-add-source > form { padding-top: 16px; }
.school-upload-actions { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding-top: 18px; border-top: 1px solid var(--line); }
.school-upload-actions .field-help { margin: 0; font-size: 14px; }
.school-sources-heading { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-top: 24px; padding-top: 24px; border-top: 1px solid var(--line); }
.school-sources-heading h3 { font-size: 16px; }
.school-sources-heading > span { color: var(--muted); font-size: 13px; }
.source-list { margin-top: 12px; }
.source-list > details { border: 1px solid var(--line); border-radius: 8px; background: var(--surface-soft); padding: 0 16px; }
.source-list > details > summary { padding-block: 12px; font-weight: 500; font-size: 15px; }
.source-list > details[open] { padding-bottom: 16px; }
.source-list .evidence-block { max-height: 240px; }
.source-recovery p, .publication-scope p { margin-block: 6px; }
.source-recovery li { margin-block: 8px; overflow-wrap: anywhere; }
.source-recovery li .text-button { margin-inline-start: 12px; }
.publication-scope { padding: 14px 16px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-soft); margin-block: 16px; }
.school-profile-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 16px; }
.school-profile-list li { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; padding: 18px; border: 1px solid var(--line); border-radius: 8px; background: var(--brand-soft); }
.school-profile-list li > div { min-width: 0; flex: 1 1 240px; overflow-wrap: anywhere; }
.school-profile-list .field-help { margin-block: 4px 0; }
.school-profile-list .button { white-space: normal; }
.draft-toolbar, .draft-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.draft-toolbar { margin-bottom: 16px; padding: 12px 14px; background: var(--surface-soft); border-radius: 8px; }
.draft-toolbar .field-help { flex: 1 1 240px; margin: 0; }
.draft-recovery p { margin-top: 0; }
.requirement-filters { margin-top: 20px; }
.requirement-workbench { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 34%); gap: 20px; align-items: start; }
.requirement-fields { min-width: 0; grid-column: 1; grid-row: 1; }
.requirement-workbench > :deep(.school-source-context) { grid-column: 2; grid-row: 1; }
.source-context-link { margin-bottom: 12px; }
@container workspace (max-width: 1100px) { .requirement-workbench { grid-template-columns: minmax(0, 1fr); gap: 12px; } .requirement-fields { grid-row: 2; } .requirement-workbench > :deep(.school-source-context) { grid-column: 1; grid-row: 1; } }
.requirement-editor { padding: 0; margin-top: 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); overflow: hidden; }
.requirement-editor.requirement-conflict { border-color: var(--warning-line); }
.requirement-disclosure > summary { display: flex; align-items: center; gap: 12px; list-style: none; padding: 15px 18px; cursor: pointer; }
.requirement-disclosure > summary::-webkit-details-marker { display: none; }
.requirement-disclosure > summary:hover { background: var(--surface-hover); }
.requirement-disclosure > summary :deep(svg) { width: 17px; height: 17px; color: var(--subtle); flex: none; }
.requirement-disclosure[open] > summary { border-bottom: 1px solid var(--line); }
.requirement-disclosure[open] > summary :deep(svg) { transform: rotate(90deg); }
.requirement-order { flex: none; display: grid; place-items: center; min-width: 28px; height: 28px; padding-inline: 4px; border: 1px solid var(--line); border-radius: 7px; color: var(--muted); background: var(--surface-soft); font-size: 13px; }
.requirement-summary-text { flex: 1; min-width: 0; }
.requirement-summary-text strong, .requirement-summary-text small { display: block; overflow-wrap: anywhere; }
.requirement-summary-text strong { font-size: 15px; font-weight: 600; }
.requirement-summary-text small { color: var(--muted); font-size: 13px; margin-top: 2px; }
.requirement-state { flex: none; font-size: 12px; color: var(--muted); background: var(--surface-soft); border-radius: 5px; padding: 2px 8px; }
.requirement-confirmed .requirement-state { color: var(--success); background: var(--success-bg); }
.requirement-state.conflict { color: var(--warning); background: var(--warning-bg); }
.requirement-edit-body { padding: 20px; }
.requirement-edit-body > .form-group:last-child { margin-bottom: 0; }
.form-group > summary { min-height: 44px; padding-block: 10px; cursor: pointer; font-size: 15px; color: var(--brand); }
.form-group > summary:focus-visible { outline: 3px solid var(--focus); outline-offset: 3px; border-radius: 6px; }
@container workspace (max-width: 800px) { .school-steps > button { padding: 14px 12px; gap: 8px; } .school-steps small { display: none; } .school-steps > button > :deep(svg) { display: none; } }
@container workspace (max-width: 640px) { .school-picker { grid-template-columns: minmax(0, 1fr); gap: 12px; } .school-picker .button { justify-self: start; } .school-step-number { width: 24px; height: 24px; } .school-steps > button { flex-direction: column; text-align: center; min-height: 88px; padding: 12px 8px; } .school-steps strong { font-size: 15px; } .school-steps > button > span:not(.school-step-number) { flex: none; } .school-upload-actions > .field-help { flex-basis: 100%; } .school-upload-actions > .button { width: 100%; } .requirement-disclosure > summary { padding: 14px 12px; gap: 8px; } .requirement-edit-body { padding: 16px; } .materials-panel, .school-picker { padding: 20px; } }
@media (max-width: 480px) { .school-picker { grid-template-columns: minmax(0, 1fr); gap: 12px; } .school-steps > button { flex-direction: column; text-align: center; min-height: 88px; padding: 12px 8px; gap: 8px; } .school-steps small, .school-steps > button > :deep(svg) { display: none; } .school-steps > button > span:not(.school-step-number) { flex: none; } .materials-panel, .school-picker { padding: 20px; } .school-profile-list li { padding: 14px; } .school-profile-list .button { width: 100%; } }
</style>
