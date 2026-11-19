<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import AppShell from './components/AppShell.vue'
import WorkspaceNav from './components/WorkspaceNav.vue'
import NewAuditView from './views/NewAuditView.vue'
import BatchAuditView from './views/BatchAuditView.vue'
import HistoryView from './views/HistoryView.vue'
import ResultView from './views/ResultView.vue'
import ProfilesView from './views/ProfilesView.vue'
import PluginsView from './views/PluginsView.vue'
import DoctorView from './views/DoctorView.vue'
import SchoolsView from './views/SchoolsView.vue'
import CollectionsView from './views/CollectionsView.vue'
import { useAuditStore } from './composables/useAuditStore'
import { useAuditDraft } from './composables/useAuditDraft'
import { backgroundBatchError, backgroundBatchId } from './composables/useBatchAudit'
import { backgroundRepairError, backgroundRepairJob } from './composables/useDocumentRepair'
import { backgroundTrialError, backgroundTrialJobId } from './composables/useProfileTrial'
import { useSingleAuditActions } from './composables/useSingleAuditActions'
import type { SchoolDraftCache } from './composables/useRequirementEditor'
import type { ReviewDraftCache } from './utils/reportWorkspace'
import type { Job, Page, Profile } from './types'
import { auditDefaults, auditRoute } from './utils/auditRoute'

const store = useAuditStore()
const auditDraft = useAuditDraft()
const schoolDraftCache: SchoolDraftCache = new Map()
const reviewDraftCache: ReviewDraftCache = new Map()
const page = ref<Page>('new')
const selectedId = ref('')
const workspaceId = ref('')
const creatingSchool = ref(false)
const routeVersion = ref(0)
const { submit, retry, backgroundJob } = useSingleAuditActions({ routeVersion, route: () => window.location.hash, selectedId, draft: auditDraft, store, navigate })
const titles: Record<Page, string> = { new: '新建检测', batch: '批量检测', history: '检测记录', result: '检测结果', profiles: '规则方案', plugins: '检测能力', doctor: '运行环境', schools: '学校要求', collections: '材料分组核验' }
const title = computed(() => titles[page.value])
const openSchoolTemplate = computed(() => {
  routeVersion.value
  return /^#new(?:\?|$)/.test(window.location.hash) && new URLSearchParams(window.location.hash.split('?')[1] || '').get('source') === 'school'
})
const selectedJob = computed(() => store.selectedJob.value?.id === selectedId.value ? store.selectedJob.value : null)
const artifacts = computed(() => store.artifacts.value.get(selectedId.value) || [])

function focusMainContent() {
  void nextTick(() => document.getElementById('main-content')?.focus({ preventScroll: true }))
}

function routeFromHash() {
  routeVersion.value += 1
  const route = window.location.hash.slice(1) || 'new'
  const defaults = auditDefaults(route)
  if (defaults && route.includes('?')) auditDraft.applyDefaults(defaults)
  if (defaults) auditDraft.revisionOf.value = new URLSearchParams(route.split('?')[1]).get('revision') || ''
  creatingSchool.value = route === 'schools/new'
  const match = route.match(/^job\/([A-Za-z0-9_-]+)$/)
  if (match) {
    page.value = 'result'; selectedId.value = match[1]; document.title = `Formatly · ${titles.result}`; store.selectJob(selectedId.value); void store.loadJob(selectedId.value); window.scrollTo({ top: 0, behavior: 'auto' }); focusMainContent(); return
  }
  const workspaceRoute = route.match(/^(schools|collections|batch)\/([A-Za-z0-9_-]+)$/)
  workspaceId.value = creatingSchool.value ? '' : workspaceRoute?.[2] || ''
  page.value = defaults ? 'new' : workspaceRoute ? workspaceRoute[1] as Page : (['new', 'batch', 'history', 'profiles', 'plugins', 'doctor', 'schools', 'collections'].includes(route) ? route : 'new') as Page
  document.title = `Formatly · ${titles[page.value]}`
  store.clearSelection()
  if (page.value === 'doctor') void store.loadDoctor()
  window.scrollTo({ top: 0, behavior: 'auto' })
  focusMainContent()
}
function navigate(route: string) { const hash = `#${route.replace(/^#/, '')}`; if (window.location.hash !== hash) routeVersion.value += 1; window.location.hash = hash }
async function refreshArtifacts() { if (selectedId.value) await store.loadArtifacts(selectedId.value) }
function repaired(job: Job) { navigate(`job/${job.id}`); void store.refresh() }
function uploadRevision() {
  const job = selectedJob.value
  auditDraft.clearFiles()
  auditDraft.applyDefaults({ profile: job?.profile_id || '', kind: job?.kind || 'thesis', collection: job?.collection_id || '' })
  navigate(auditRoute(job?.profile_id, job?.kind, job?.collection_id, job?.id))
}
function addToCollection(id: string) { navigate(auditRoute(auditDraft.profileId.value, auditDraft.kind.value, id)) }
function useProfile(profile: Profile) { navigate(auditRoute(profile.id, profile.kinds?.includes(auditDraft.kind.value as 'thesis' | 'intern' | 'certificate') ? auditDraft.kind.value : profile.kinds?.[0])) }
function profilesConfirmed(profiles: Profile[]) { store.acceptProfiles(profiles) }
function dismissBackgroundBatch() { backgroundBatchId.value = null }
function dismissBackgroundBatchError() { backgroundBatchError.value = null }
function dismissBackgroundRepair() { backgroundRepairJob.value = null }
function dismissBackgroundRepairError() { backgroundRepairError.value = null }
function dismissBackgroundTrial() { backgroundTrialJobId.value = null }
function dismissBackgroundTrialError() { backgroundTrialError.value = null }

function beforeUnload(event: BeforeUnloadEvent) {
  if (!reviewDraftCache.size && ![...schoolDraftCache.values()].some(item => !item.saved)) return
  event.preventDefault(); event.returnValue = ''
}
onMounted(() => { window.addEventListener('hashchange', routeFromHash); window.addEventListener('beforeunload', beforeUnload); routeFromHash(); void store.refresh(true) })
onUnmounted(() => { window.removeEventListener('hashchange', routeFromHash); window.removeEventListener('beforeunload', beforeUnload); store.dispose() })
</script>
<template>
  <AppShell :page="page" :title="title" :history-count="store.stats.value.total" :loading="store.loading.value" @navigate="navigate" @refresh="store.refresh()">
    <p class="visually-hidden" aria-live="polite" aria-atomic="true">{{ title }}</p>
    <div v-if="store.error.value" class="notice error-notice global-error" role="alert" aria-live="assertive">{{ store.error.value }} <button type="button" class="text-button" @click="store.error.value = ''">关闭</button></div>
    <div v-if="store.notice.value" class="notice neutral-notice" role="status">{{ store.notice.value }} <button class="text-button" type="button" @click="store.notice.value = ''">关闭</button></div>
    <div v-if="backgroundJob" class="notice neutral-notice" role="status">检测任务已创建。<a :href="`#job/${backgroundJob.id}`">查看任务</a> <button class="text-button" type="button" @click="backgroundJob = null">关闭</button></div>
    <div v-if="backgroundBatchId" class="notice neutral-notice" role="status">批量检测已创建。<a :href="`#batch/${backgroundBatchId}`">查看批次</a> <button class="text-button" type="button" @click="dismissBackgroundBatch">关闭</button></div>
    <div v-if="backgroundBatchError" class="notice error-notice" role="alert">批量检测未完成：{{ backgroundBatchError }} <button class="text-button" type="button" @click="dismissBackgroundBatchError">关闭</button></div>
    <div v-if="backgroundRepairJob" class="notice neutral-notice" role="status">修复复检已创建。<a :href="`#job/${backgroundRepairJob.id}`">查看任务</a> <button class="text-button" type="button" @click="dismissBackgroundRepair">关闭</button></div>
    <div v-if="backgroundRepairError" class="notice error-notice" role="alert">修复未完成：{{ backgroundRepairError }} <button class="text-button" type="button" @click="dismissBackgroundRepairError">关闭</button></div>
    <div v-if="backgroundTrialJobId" class="notice neutral-notice" role="status">方案试跑已创建。<a :href="`#job/${backgroundTrialJobId}`">查看任务</a> <button class="text-button" type="button" @click="dismissBackgroundTrial">关闭</button></div>
    <div v-if="backgroundTrialError" class="notice error-notice" role="alert">方案试跑未完成：{{ backgroundTrialError }} <button class="text-button" type="button" @click="dismissBackgroundTrialError">关闭</button></div>
    <div v-for="warning in store.profileWarnings.value" :key="warning.file" class="notice warm-notice" role="alert">方案 {{ warning.file }} 未加载：{{ warning.message }}</div>
    <WorkspaceNav :page="page" />
    <NewAuditView :stats="store.stats.value" v-if="page === 'new'" :draft="auditDraft" :profiles="store.profiles.value" :jobs="store.jobs.value" :busy="store.submitting.value" :open-school="openSchoolTemplate" @submit="submit" @navigate="navigate" />
    <BatchAuditView v-else-if="page === 'batch'" :profiles="store.profiles.value" :selected-id="workspaceId" @navigate="navigate" />
    <HistoryView v-else-if="page === 'history'" :refresh-token="store.refreshVersion.value" @open="navigate(`job/${$event}`)" />
    <ResultView v-else-if="page === 'result'" :review-draft-cache="reviewDraftCache" :job="selectedJob" :artifacts="artifacts" :error="store.jobError.value" :loading="store.jobLoading.value" :retrying="store.retrying.value" :artifacts-loading="store.artifactsLoading.value" @reload="store.loadJob(selectedId)" @back="navigate('history')" @retry="retry" @load-artifacts="refreshArtifacts" @new-draft="uploadRevision" @repaired="repaired" />
    <ProfilesView v-else-if="page === 'profiles'" :profiles="store.profiles.value" :plugins="store.plugins.value" :saving="store.profileSaving.value" :save-error="store.profileError.value" :save-version="store.profileSaveVersion.value" @save="store.saveProfile" @use-profile="useProfile" @open-job="navigate(`job/${$event}`)" @clear-error="store.profileError.value = ''" />
    <PluginsView v-else-if="page === 'plugins'" :plugins="store.plugins.value" />
    <SchoolsView v-else-if="page === 'schools'" :draft-cache="schoolDraftCache" :selected-id="workspaceId" :create-new="creatingSchool" :profiles="store.profiles.value" :refresh-token="store.refreshVersion.value" @select="navigate($event ? `schools/${$event}` : 'schools')" @confirmed="profilesConfirmed" @use-profile="useProfile" @navigate="navigate" />
    <CollectionsView v-else-if="page === 'collections'" :selected-id="workspaceId" :refresh-token="store.refreshVersion.value" @select="navigate($event ? `collections/${$event}` : 'collections')" @open="navigate(`job/${$event}`)" @add="addToCollection" />
    <DoctorView v-else :report="store.doctor.value" :loading="store.doctorLoading.value" @refresh="store.loadDoctor" />
  </AppShell>
</template>
