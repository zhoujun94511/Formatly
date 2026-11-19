<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { Job, JobStats, Profile } from '../types'
import UploadDropzone from '../components/UploadDropzone.vue'
import AppIcon from '../components/AppIcon.vue'
import StatCard from '../components/StatCard.vue'
import StatusBadge from '../components/StatusBadge.vue'
import DocumentCapabilities from '../components/DocumentCapabilities.vue'
import ProfileSummary from '../components/ProfileSummary.vue'
import WorkspaceWarnings from '../components/WorkspaceWarnings.vue'
import DocumentScopePicker from '../components/DocumentScopePicker.vue'
import { useAuditSetup } from '../composables/useAuditSetup'
import { useDocumentScope } from '../composables/useDocumentScope'
import { useDocumentCapabilities } from '../composables/useDocumentCapabilities'
import type { AuditDraft } from '../composables/useAuditDraft'
import { api } from '../api'
import { documentKinds, isHiddenPreset, profileLabel, profileMatchesKind } from '../utils/materials'
import { documentFileError } from '../utils/documents'
import { formatDateTime } from '../utils/date'
import { profileRuleSignature } from '../utils/profileSignature'
import { scopeSummaryOverlay } from '../utils/scopeSummary'

const props = defineProps<{
  profiles: Profile[]
  jobs: Job[]
  stats?: JobStats
  busy?: boolean
  draft: AuditDraft
  openSchool?: boolean
}>()
const emit = defineEmits<{ submit: [FormData]; navigate: [string] }>()
const files = props.draft.files
const { documentFile, pdfFile, pdfError, inputFormat, canPairPdf } = files
const pdfInput = ref<HTMLInputElement>()
const pdfPicker = ref<HTMLButtonElement>()
const schoolFile = ref<File | null>(null)
const schoolUploadError = ref('')
const schoolUploading = ref(false)
let pendingSchoolId = ''
const { profileId, kind, collectionId, renderWord } = props.draft
const selectedProfile = computed(() => props.profiles.find(profile => profile.id === profileId.value))
const matchingProfiles = computed(() => props.profiles.filter(profile => profileMatchesKind(profile, kind.value) && (!isHiddenPreset(profile) || profile.id === profileId.value && profile.id === 'school-specific')))
const ruleSource = ref<'preset' | 'school'>(props.openSchool ? 'school' : 'preset')
watch(() => props.openSchool, open => { ruleSource.value = open ? 'school' : 'preset' })
watch(kind, () => {
  if (selectedProfile.value && !profileMatchesKind(selectedProfile.value, kind.value)) profileId.value = ''
})
const ruleSignature = computed(() => profileRuleSignature(selectedProfile.value))
const setup = useAuditSetup(profileId, kind, inputFormat, ruleSignature)
const { preflight, checking, ready, error: preflightError, collections, collectionError, collectionWarnings } = setup
const documentScope = useDocumentScope(documentFile, profileId, kind, ruleSignature, preflight)
const scopeSummary = computed(() => {
  if (!preflight.value?.summary) return null
  if (!documentScope.preview.value || documentScope.expired.value) return { summary: preflight.value.summary, updated: 0 }
  return scopeSummaryOverlay(preflight.value.summary, documentScope.requirements.value, documentScope.bindings.value, preflight.value.available)
})
const scopeDecisions = computed(() => Object.values(documentScope.bindings.value).reduce((counts, binding) => {
  counts[binding.status === 'bound' ? 'bound' : 'manual']++; return counts
}, { bound: 0, manual: 0 }))
const formError = ref('')
const usesLegacy = computed(() => selectedProfile.value?.plugins?.includes('legacy-school') ?? false)
const office = useDocumentCapabilities()
const canRenderWord = computed(() => canPairPdf.value && (usesLegacy.value || !pdfFile.value && office.capabilities.value?.office?.available === true))
const submitHint = computed(() => {
  if (!documentFile.value) return '请选择待检测原稿。'
  if (!selectedProfile.value) return '请选择适用的规则方案。'
  if (checking.value) return '正在检查方案，请稍候。'
  if (!ready.value) return '方案尚不可用，请处理上方提示。'
  if (!documentScope.ready.value) return '请逐条确认原稿范围，或选择暂不匹配。'
  if (collectionId.value && collectionError.value) return '请先重新读取关联的材料集合。'
  return ''
})

watch(canRenderWord, enabled => {
  if (!enabled) renderWord.value = false
})
watch([documentFile, pdfFile, profileId, kind, collectionId, collectionError, renderWord], () => { formError.value = '' })

function choosePdf(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (props.busy || !file) return
  files.choosePdf(file)
}

function removePdf() {
  if (props.busy) return
  if (pdfInput.value) pdfInput.value.value = ''
  files.removePdf()
  void nextTick(() => pdfPicker.value?.focus())
}

function schoolNameFromFile(file: File) {
  const stem = file.name.replace(/\.[^.]+$/, '').trim()
  return (stem || '学校要求').slice(0, 120)
}

async function uploadSchoolFile(file: File | null) {
  if (!file || schoolUploading.value || props.busy) return
  schoolUploading.value = true
  schoolUploadError.value = ''
  try {
    if (!pendingSchoolId) {
      const school = await api.createSchool(schoolNameFromFile(file))
      pendingSchoolId = school.id
    }
    const body = new FormData()
    body.append('source', file)
    body.append('kind', kind.value)
    body.append('role', 'template')
    const saved = await api.addSchoolSource(pendingSchoolId, body)
    pendingSchoolId = ''
    schoolFile.value = null
    emit('navigate', `schools/${saved.id}`)
  } catch (error) {
    schoolUploadError.value = error instanceof Error ? error.message : '学校要求上传失败，请重试。'
  } finally {
    schoolUploading.value = false
  }
}

watch(schoolFile, file => { if (file) void uploadSchoolFile(file) })

function submit() {
  if (props.busy || ruleSource.value !== 'preset') return
  formError.value = ''
  if (!documentFile.value) {
    formError.value = '请先选择要检测的文档。'
    return
  }
  const validation = documentFileError(documentFile.value)
  if (validation) { formError.value = validation; return }
  if (pdfError.value) {
    formError.value = '请重新选择有效的 PDF，或移除配对 PDF 后继续。'
    return
  }
  if (!selectedProfile.value) {
    formError.value = '请先选择一个有效的规则方案。'
    return
  }
  if (!ready.value) {
    formError.value = '请等待方案能力检查通过，或根据提示修复缺失依赖。'
    return
  }
  if (collectionId.value && collectionError.value) {
    formError.value = '请先重新读取关联的材料集合。'
    return
  }
  if (!documentScope.ready.value) { formError.value = '请先读取原稿范围，并逐条确认或选择暂不匹配。'; return }
  const data = new FormData()
  const scopeBindings = documentScope.payload()
  if (scopeBindings && documentScope.preview.value) {
    data.append('preview_id', documentScope.preview.value.id)
    data.append('scope_bindings', JSON.stringify(scopeBindings))
    documentScope.markSubmitted()
  } else data.append('document', documentFile.value)
  if (canPairPdf.value && pdfFile.value) data.append('pdf', pdfFile.value)
  data.append('profile_id', profileId.value)
  data.append('kind', kind.value)
  if (collectionId.value) data.append('collection_id', collectionId.value)
  data.append('render_word', canRenderWord.value && renderWord.value ? 'true' : 'false')
  emit('submit', data)
}
</script>

<template>
  <div class="page new-audit-page">
    <div class="page-heading">
      <div>
        <h1>新建检测</h1>
        <p>选择预置方案或学校模板，再检测原稿。</p>
      </div>
      <button class="button secondary" type="button" :disabled="busy" @click="emit('navigate', 'batch')"><AppIcon name="layers" :size="18" />批量检测</button>
    </div>
    <p v-if="draft.revisionOf.value" class="notice neutral-notice">本次将与原检测关联。<button type="button" class="text-button" @click="emit('navigate', `job/${draft.revisionOf.value}`)">查看原检测</button></p>
    <form class="panel audit-flow" :aria-busy="!!busy" @submit.prevent="submit">
      <div class="form-group">
        <label for="kind-select">文档类型</label>
        <select id="kind-select" v-model="kind" :disabled="busy || !!draft.revisionOf.value">
          <option v-for="item in documentKinds" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </div>
      <div class="rule-source" role="radiogroup" aria-label="规则来源">
        <label><input v-model="ruleSource" type="radio" value="preset" :disabled="busy" /><span><strong>预置方案</strong><small>选好方案，上传原稿，直接检测</small></span></label>
        <label><input v-model="ruleSource" type="radio" value="school" :disabled="busy || schoolUploading" /><span><strong>学校模板</strong><small>上传学校文件，核对后用来检测</small></span></label>
      </div>
      <template v-if="ruleSource === 'preset'">
        <div class="form-group">
          <label for="profile-select">规则方案</label>
          <select id="profile-select" v-model="profileId" :disabled="busy">
            <option value="">请选择方案</option>
            <option v-for="profile in matchingProfiles" :key="profile.id" :value="profile.id">{{ profileLabel(profile) }}</option>
          </select>
        </div>
        <div v-if="profileId && (checking || preflightError || preflight && (!preflight.available || preflight.warnings?.length || preflight.plugins.some(item => item.available === false)))" class="preflight-status" :aria-busy="checking">
          <p v-if="checking" class="notice neutral-notice" role="status">正在检查方案所需能力…</p>
          <p v-else-if="preflightError" class="notice error-notice" role="alert">{{ preflightError }} <button class="text-button" type="button" @click="setup.check">重新检查</button></p>
          <template v-else-if="preflight"><p v-if="!preflight.available" class="notice error-notice" role="alert">方案无法执行，请检查以下问题。</p><p v-for="plugin in preflight.plugins.filter(item => item.available === false)" :key="plugin.id" class="notice warm-notice">{{ plugin.name || plugin.id }}：{{ plugin.reason || '当前不可用' }}</p><p v-for="warning in preflight.warnings" :key="warning" class="notice warm-notice">{{ warning }}</p></template>
        </div>
        <div class="form-group">
          <div class="panel-heading manuscript-heading"><label id="manuscript-label">待检测原稿</label><span class="muted micro">单件 ≤ 40 MB</span></div>
          <UploadDropzone v-model="documentFile" label="待检测原稿" :disabled="busy" />
        </div>
        <p v-if="documentFile && ['txt', 'md', 'json'].includes(inputFormat)" class="field-help">此格式仅检测文本内容与结构。</p>
        <DocumentCapabilities v-if="inputFormat === 'pdf' || pdfFile" />
        <details v-if="documentFile && canPairPdf" class="pdf-option">
          <summary>附加 PDF <span class="optional-label">可选</span></summary>
          <p id="pdf-help" class="field-help">添加由此文档导出的 PDF。</p>
          <input
            id="pdf-input"
            ref="pdfInput"
            class="visually-hidden"
            tabindex="-1"
            type="file"
            accept=".pdf"
            aria-label="选择配对 PDF"
            :disabled="busy"
            :aria-invalid="!!pdfError"
            :aria-describedby="pdfError ? 'pdf-help pdf-error' : 'pdf-help'"
            @change="choosePdf"
          />
          <button
            ref="pdfPicker"
            class="button secondary pdf-picker"
            type="button"
            :disabled="busy"
            :aria-invalid="!!pdfError"
            :aria-describedby="pdfError ? 'pdf-help pdf-error' : 'pdf-help'"
            @click="pdfInput?.click()"
          >{{ pdfFile ? '更换 PDF' : '选择 PDF' }}</button>
          <div v-if="pdfFile" class="selected-file">
            <span class="file-icon"><AppIcon name="file" :size="19" /></span>
            <div><strong>{{ pdfFile.name }}</strong><small>配对 PDF · 已就绪</small></div>
            <button type="button" class="icon-button" aria-label="移除配对 PDF" :disabled="busy" @click="removePdf"><AppIcon name="close" :size="18" /></button>
          </div>
          <p v-if="pdfError" id="pdf-error" class="notice error-notice" role="alert">{{ pdfError }}</p>
          <button v-if="pdfError" type="button" class="text-button" :disabled="busy" @click="removePdf">移除配对 PDF</button>
        </details>
        <DocumentScopePicker v-if="documentScope.needsScope.value" :workspace="documentScope" :disabled="busy" :has-file="!!documentFile" />
        <template v-if="scopeSummary && !checking"><p v-if="documentScope.needsScope.value" class="field-help scope-summary-note" role="status">{{ scopeSummary.updated ? `已叠加 ${scopeSummary.updated} 条本次范围选择。` : '方案预检，未计本次范围确认。' }}<template v-if="documentScope.preview.value && !documentScope.expired.value">已确认 {{ scopeDecisions.bound }} 条范围 · {{ scopeDecisions.manual }} 条暂不匹配。</template>实际执行与符合情况以检测报告为准。</p><ProfileSummary :summary="scopeSummary.summary" /></template>
        <details class="audit-extra-options" :open="!!collectionId || !!collectionError">
          <summary>更多选项 <span class="optional-label">关联材料、生成 PDF</span></summary>
        <WorkspaceWarnings :warnings="collectionWarnings" label="材料集合" />
        <div class="form-group"><label for="collection-select">关联材料集合 <span class="optional-label">可选</span></label><select id="collection-select" v-model="collectionId" :disabled="busy || !!collectionError"><option value="">不关联，单篇检测</option><option v-for="collection in collections" :key="collection.id" :value="collection.id">{{ collection.name }}</option></select><p v-if="collectionError" class="notice error-notice" role="alert">{{ collectionError }} <button class="text-button" type="button" @click="setup.loadCollections">重读集合</button></p><button class="text-button" type="button" :disabled="busy" @click="emit('navigate', 'collections')">管理材料集合</button></div>
        <div v-if="usesLegacy" class="notice warm-notice">适用范围由用户提供的学校依据与规则方案决定。</div>
        <label v-if="canPairPdf" class="checkbox-row">
          <input v-model="renderWord" type="checkbox" :disabled="busy || !canRenderWord" />
          <span>使用本机 Word / WPS 生成 PDF<small>{{ pdfFile && !usesLegacy ? '已添加配对 PDF，无需重复生成。' : '只读导出，原稿保持不变。' }}</small></span>
        </label>
        <p v-if="canPairPdf && !usesLegacy && !pdfFile && !canRenderWord" class="field-help" role="status">{{ office.loading.value ? '正在检查本机导出能力…' : office.error.value || office.capabilities.value?.office?.reason || '本机导出能力暂不可用。' }} <button v-if="!office.loading.value" class="text-button" type="button" :disabled="busy" @click="office.refresh">重新检查</button></p>
        </details>
        <div class="audit-submit-area">
        <p v-if="formError" class="notice error-notice" role="alert">{{ formError }}</p>
        <p v-else-if="submitHint" id="audit-submit-hint" class="field-help" role="status">{{ submitHint }}</p>
        <button
          class="button primary submit-button"
          :disabled="busy || !documentFile || !selectedProfile || !!pdfError || !ready || !documentScope.ready.value || (!!collectionId && !!collectionError)"
          type="submit"
          :aria-describedby="submitHint ? 'audit-submit-hint' : undefined"
        >
          <span>{{ busy ? '正在提交文档…' : '开始格式检测' }}</span><AppIcon name="arrow-right" :size="18" />
        </button>
        </div>
      </template>
      <div v-else class="form-group">
        <p id="school-template-help" class="field-help">按当前文档类型提取。上传后直接核对，确认后即可回来检测。</p>
        <UploadDropzone v-model="schoolFile" label="学校模板或格式说明" :disabled="busy || schoolUploading" />
        <p v-if="schoolUploading" class="field-help" role="status">正在上传并提取要求…</p>
        <p v-if="schoolUploadError" class="notice error-notice" role="alert">{{ schoolUploadError }} <button class="text-button" type="button" :disabled="busy || schoolUploading || !schoolFile" @click="uploadSchoolFile(schoolFile)">重新上传</button></p>
      </div>
    </form>
    <div class="stat-grid audit-statistics">
      <StatCard label="累计检测" :value="stats?.total ?? '—'" tone="neutral" icon="file" />
      <StatCard label="检测完成" :value="stats?.completed ?? '—'" tone="green" icon="check" />
      <StatCard label="待修正" :value="stats?.needs_changes ?? '—'" tone="coral" icon="alert" />
    </div>
    <section class="recent-section">
      <div class="section-heading"><h2>最近检测</h2><button class="text-button" type="button" @click="emit('navigate', 'history')">查看全部<AppIcon name="arrow-right" :size="16" /></button></div>
      <div class="panel job-list">
        <button v-for="job in jobs.slice(0, 4)" :key="job.id" type="button" class="job-row" @click="emit('navigate', `job/${job.id}`)">
          <span class="job-file-icon"><AppIcon name="file" /></span>
          <span class="job-row-main"><strong>{{ job.filename || '未命名文档' }}</strong><small>{{ formatDateTime(job.created_at) }}</small></span>
          <span class="job-status-stack"><StatusBadge :status="job.status" /><StatusBadge v-if="job.result?.status" :status="job.result.status" /></span><span aria-hidden="true"><AppIcon name="chevron-right" :size="18" /></span>
        </button>
        <div v-if="!jobs.length" class="empty-state recent-empty"><AppIcon name="history" :size="25" /><span>还没有检测记录</span></div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.pdf-option { padding-top: 10px; border-top: 1px solid var(--line); }
.pdf-option > summary, .form-details > summary { min-height: 44px; padding-block: 10px; cursor: pointer; font-size: 15px; }
.pdf-option > summary { font-weight: 700; }
.form-details > summary { color: var(--muted); }
summary:focus-visible { outline: 3px solid var(--focus); outline-offset: 3px; border-radius: 6px; }
.pdf-picker { margin-top: 12px; }
.audit-flow { display: flex; flex-direction: column; gap: 16px; padding: var(--panel-padding); }
.audit-flow > .form-group { margin: 0; }
.rule-source { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.rule-source label { display: flex; gap: 10px; align-items: flex-start; min-width: 0; margin: 0; padding: 12px 14px; border: 1px solid var(--line); border-radius: 8px; cursor: pointer; }
.rule-source label:has(input:checked) { border-color: var(--brand); background: var(--brand-soft); }
.rule-source input { margin-top: 3px; }
.rule-source strong, .rule-source small { display: block; }
.rule-source small { margin-top: 2px; color: var(--muted); font-size: 13px; line-height: 1.4; }
.manuscript-heading { margin-bottom: 8px; }
.audit-flow :deep(.dropzone) { min-height: 0; flex-direction: row; flex-wrap: wrap; justify-content: flex-start; align-items: center; gap: 6px 12px; padding: 12px 14px; text-align: left; }
.audit-flow :deep(.dropzone strong) { margin-top: 0; font-size: 15px; }
.audit-flow :deep(.upload-illustration) { width: 36px; height: 36px; border-radius: 8px; }
.audit-flow :deep(.upload-illustration .app-icon) { width: 18px; height: 18px; }
.audit-flow :deep(.file-type-badge) { margin-top: 0; }
.audit-statistics { margin-top: 28px; }
.recent-section { margin-top: 28px; }
.audit-submit-area { padding-top: 16px; border-top: 1px solid var(--line); }
.audit-submit-area > .field-help { margin: 0 0 10px; font-size: 13px; }
.audit-extra-options { margin: 0; }
.audit-extra-options > summary { cursor: pointer; padding-block: 10px; font-size: 14px; min-height: 44px; }
.audit-extra-options > .form-group { margin-top: 12px; }
.audit-statistics { padding-block: 2px; border-block: 1px solid var(--line); margin-bottom: 0; }
.recent-empty { display: flex; justify-content: center; align-items: center; gap: 12px; padding: 30px 20px; }
@media (max-width: 640px) { .rule-source { grid-template-columns: 1fr; } }
</style>
