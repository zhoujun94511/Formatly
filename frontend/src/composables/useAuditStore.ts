import { computed, reactive, ref } from 'vue'
import { api } from '../api'
import type { Artifact, DoctorReport, Job, JobStats, Plugin, Profile, ProfileWarning } from '../types'

const busy = (job: Job | null) => !!job && ['queued', 'running'].includes(job.status)

// Each app owns its requests and timers; disposing one app cannot disable another.
export function useAuditStore(client = api) {
  const state = reactive({ profiles: [] as Profile[], plugins: [] as Plugin[], jobs: [] as Job[], selectedJob: null as Job | null, artifacts: new Map<string, Artifact[]>() })
  const stats = ref<JobStats>({ total: 0, completed: 0, needs_changes: 0 })
  const loading = ref(false), doctorLoading = ref(false), submitting = ref(false), retrying = ref(false), jobLoading = ref(false), profileSaving = ref(false)
  const doctor = ref<DoctorReport | null>(null)
  const notice = ref(''), error = ref(''), jobError = ref(''), profileError = ref('')
  const profileWarnings = ref<ProfileWarning[]>([])
  const profileSaveVersion = ref(0), refreshVersion = ref(0)
  const activeJobId = ref<string | null>(null)
  const artifactRequests = new Map<string, Promise<Artifact[]>>()
  const artifactsInFlight = reactive(new Set<string>())
  const artifactsLoading = computed(() => !!activeJobId.value && artifactsInFlight.has(activeJobId.value))
  let selectedRequest = 0, profileRevision = 0, jobsRevision = 0, jobsRead = 0, pluginsRead = 0
  let pollTimer: ReturnType<typeof window.setTimeout> | undefined
  let disposed = false, pollBusy = false

  function message(value: unknown) { return value instanceof Error ? value.message : String(value) }
  function setError(value: unknown) { if (!disposed) error.value = message(value) }
  function upsert(job: Job) {
    const index = state.jobs.findIndex(item => item.id === job.id)
    if (index < 0) state.jobs.unshift(job); else state.jobs[index] = job
  }
  function acceptProfiles(profiles: Profile[]) {
    if (disposed) return
    profileRevision += 1
    state.profiles = [...new Map([...state.profiles, ...profiles].map(item => [item.id, item])).values()]
  }
  function clearPoll() { window.clearTimeout(pollTimer); pollTimer = undefined }
  function schedulePoll() {
    clearPoll()
    if (!disposed && !pollBusy && [...state.jobs, state.selectedJob].some(busy)) pollTimer = window.setTimeout(poll, 1800)
  }
  async function readJobs() {
    const request = ++jobsRead, revision = jobsRevision
    const data = await client.jobs()
    if (disposed || request !== jobsRead) return
    if (revision !== jobsRevision) return readJobs()
    state.jobs = data.items; stats.value = data.stats
  }
  async function readPlugins() {
    const request = ++pluginsRead
    const data = await client.plugins()
    if (!disposed && request === pluginsRead) state.plugins = data.items
  }
  async function refresh(silent = false) {
    if (loading.value || disposed) return
    loading.value = true; error.value = ''
    const revision = profileRevision
    // Apply each resource as it arrives, without waiting for a slow optional engine probe.
    const results = await Promise.allSettled([
      client.profiles().then(data => { if (!disposed) { state.profiles = revision === profileRevision ? data.items : [...new Map([...data.items, ...state.profiles].map(item => [item.id, item])).values()]; if (revision === profileRevision) profileWarnings.value = data.warnings || [] } }),
      readPlugins(),
      readJobs()
    ])
    if (disposed) return
    const errors = results.filter((item): item is PromiseRejectedResult => item.status === 'rejected').map(item => message(item.reason))
    if (errors.length) error.value = [...new Set(errors)].join(' ')
    else if (!silent) notice.value = '已刷新'
    loading.value = false; refreshVersion.value += 1; schedulePoll()
  }
  function clearSelection() { activeJobId.value = null; selectedRequest += 1; state.selectedJob = null; jobLoading.value = false; jobError.value = ''; schedulePoll() }
  function selectJob(id: string) {
    clearSelection(); activeJobId.value = id
    // List summaries deliberately never become detail reports.
    jobLoading.value = true
  }
  async function loadJob(id: string) {
    const request = ++selectedRequest
    activeJobId.value = id; jobLoading.value = true; jobError.value = ''
    try {
      const job = await client.job(id)
      if (disposed || request !== selectedRequest || activeJobId.value !== id) return
      state.selectedJob = job; upsert(job)
      if (!busy(job)) void loadArtifacts(id)
    } catch (e) { if (!disposed && request === selectedRequest) jobError.value = message(e) }
    finally { if (!disposed && request === selectedRequest) jobLoading.value = false; schedulePoll() }
  }
  async function createJob(form: FormData) {
    if (submitting.value || disposed) return
    submitting.value = true; error.value = ''
    try {
      const previewId = form.get('preview_id')
      const job = await client.createJob(form)
      if (typeof previewId === 'string' && previewId) void client.discardDocumentPreview(previewId).catch(() => {})
      if (disposed) return
      jobsRevision += 1; upsert(job); schedulePoll(); return job
    }
    finally { if (!disposed) submitting.value = false }
  }
  async function retry(id: string) {
    if (retrying.value || disposed) return
    retrying.value = true; error.value = ''
    try { const job = await client.retry(id); if (disposed) return; jobsRevision += 1; upsert(job); schedulePoll(); return job }
    finally { if (!disposed) retrying.value = false }
  }
  function loadArtifacts(id: string): Promise<Artifact[]> {
    if (disposed) return Promise.resolve([])
    const pending = artifactRequests.get(id)
    if (pending) return pending
    artifactsInFlight.add(id)
    const request = client.artifacts(id).then(data => { if (!disposed) state.artifacts.set(id, data.items); return data.items })
      .catch(e => { if (activeJobId.value === id) setError(e); return [] as Artifact[] })
      .finally(() => { artifactRequests.delete(id); artifactsInFlight.delete(id) })
    artifactRequests.set(id, request)
    return request
  }
  async function loadDoctor() {
    if (doctorLoading.value || disposed) return
    doctorLoading.value = true; error.value = ''
    try {
      const results = await Promise.allSettled([
        client.doctor().then(report => { if (!disposed) doctor.value = report }),
        readPlugins(),
      ])
      const errors = results.filter((item): item is PromiseRejectedResult => item.status === 'rejected').map(item => message(item.reason))
      if (errors.length) setError([...new Set(errors)].join(' '))
    } catch (e) { setError(e) }
    finally { if (!disposed) doctorLoading.value = false }
  }
  async function saveProfile(profile: Profile) {
    if (profileSaving.value || disposed) return
    profileSaving.value = true; profileError.value = ''
    try {
      const saved = await client.saveProfile(profile)
      if (disposed) return
      profileRevision += 1
      const index = state.profiles.findIndex(item => item.id === saved.id)
      if (index < 0) state.profiles.push(saved); else state.profiles[index] = saved
      profileSaveVersion.value += 1; notice.value = '方案已保存'
    } catch (e) { if (!disposed) profileError.value = message(e) }
    finally { if (!disposed) profileSaving.value = false }
  }
  async function poll() {
    if (pollBusy || disposed) return
    pollBusy = true; clearPoll()
    try {
      // A list read failure must not prevent the active report from completing.
      const id = activeJobId.value, request = selectedRequest
      const results = await Promise.allSettled([
        readJobs(),
        id && busy(state.selectedJob) ? client.job(id).then(job => {
          if (disposed || activeJobId.value !== id || request !== selectedRequest) return
          state.selectedJob = job
          if (!busy(job)) void loadArtifacts(id)
        }) : Promise.resolve()
      ])
      for (const result of results) if (result.status === 'rejected') setError(result.reason)
    } finally { pollBusy = false; schedulePoll() }
  }
  function dispose() { disposed = true; clearPoll(); selectedRequest += 1; jobsRead += 1; pluginsRead += 1 }
  return { state, stats, loading, doctor, doctorLoading, submitting, retrying, jobLoading, jobError, artifactsLoading, profileSaving, profileError, profileWarnings, profileSaveVersion, refreshVersion, notice, error, refresh, acceptProfiles, selectJob, clearSelection, loadJob, createJob, retry, loadArtifacts, loadDoctor, saveProfile, dispose,
    profiles: computed(() => state.profiles), plugins: computed(() => state.plugins), jobs: computed(() => state.jobs), selectedJob: computed(() => state.selectedJob), artifacts: computed(() => state.artifacts) }
}
