import { computed, onUnmounted, reactive, ref, shallowReactive, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { api } from '../api'
import type { Job } from '../types'
import type { IssueEvidence, JobComparison, JobReviews, ReviewDraftCache, ReviewStatus } from '../utils/reportWorkspace'

const reviewSnapshots = new WeakMap<ReviewDraftCache, Map<string, JobReviews>>()
const reviewBinding = (value: Pick<JobReviews, 'job_id' | 'input_sha256' | 'profile_sha256'>) => JSON.stringify([value.job_id, value.input_sha256, value.profile_sha256])

export function useReportWorkspace(source: MaybeRefOrGetter<Job | null>, client: Pick<typeof api, 'issueEvidence' | 'jobComparison' | 'jobReviews' | 'saveJobReview'> = api, draftCache: ReviewDraftCache = new Map()) {
  let knownSnapshots = reviewSnapshots.get(draftCache)
  if (!knownSnapshots) { knownSnapshots = shallowReactive(new Map<string, JobReviews>()); reviewSnapshots.set(draftCache, knownSnapshots) }
  const snapshots = knownSnapshots
  const job = computed(() => toValue(source))
  const index = ref<number | null>(null), evidence = ref<IssueEvidence | null>(null), reviews = ref<JobReviews | null>(null)
  const comparison = ref<JobComparison | null>(null)
  const loading = ref(false), saving = ref(false), comparing = ref(false), refreshingReviews = ref(false)
  const error = ref(''), reviewError = ref(''), compareError = ref('')
  const draft = reactive({ status: 'pending' as ReviewStatus, note: '' })
  const saved = ref(false)
  const unsaved = ref(false), restoredDraft = ref(false)
  let disposed = false, generation = 0, evidenceSequence = 0, compareSequence = 0, reviewSequence = 0
  let draftChanged = false, applyingDraft = false
  const message = (value: unknown) => value instanceof Error ? value.message : String(value)
  const current = (g: number, id: string) => !disposed && generation === g && job.value?.id === id
  const eligible = computed(() => job.value?.status === 'completed' && !!job.value.result && job.value.result.status !== 'incomplete')
  const canSaveReview = computed(() => eligible.value && index.value !== null && !!evidence.value && !!reviews.value
    && !saving.value && !refreshingReviews.value && !loading.value && !reviewError.value)
  watch([() => draft.status, () => draft.note], () => {
    if (!applyingDraft) { draftChanged = true; saved.value = false; unsaved.value = true; rememberDraft() }
  }, { flush: 'sync' })
  function cacheKey(value: IssueEvidence) {
    return JSON.stringify([value.job_id, value.input_sha256, value.profile_sha256, value.issue_key])
  }
  function rememberDraft() {
    if (draftChanged && evidence.value) draftCache.set(cacheKey(evidence.value), { status: draft.status, note: draft.note })
  }
  function applyDraft(status: ReviewStatus = 'pending', note = '') {
    applyingDraft = true; draft.status = status; draft.note = note; applyingDraft = false
  }
  function restoreReview() {
    if (draftChanged || !evidence.value || !reviews.value) return
    const cached = draftCache.get(cacheKey(evidence.value))
    if (cached) {
      applyDraft(cached.status, cached.note); draftChanged = true; unsaved.value = true; restoredDraft.value = true
      return
    }
    const existing = reviews.value.items[evidence.value.issue_key]
    applyDraft(existing?.status, existing?.note)
  }
  watch([() => job.value?.id, () => job.value?.result?.input_sha256, () => job.value?.result?.profile_sha256], () => {
    rememberDraft()
    generation++; evidenceSequence++; compareSequence++; reviewSequence++
    index.value = null; evidence.value = null; reviews.value = null; comparison.value = null
    error.value = ''; reviewError.value = ''; compareError.value = ''
    loading.value = false; saving.value = false; comparing.value = false; refreshingReviews.value = false; saved.value = false
    draftChanged = false; unsaved.value = false; restoredDraft.value = false
  }, { flush: 'sync' })

  function checkReviews(value: JobReviews, id: string) {
    if (value.job_id !== id || value.input_sha256 !== job.value?.result?.input_sha256 || value.profile_sha256 !== job.value?.result?.profile_sha256) throw Error('复核记录与当前报告不一致，请重新读取。')
  }
  function rememberReviews(value: JobReviews) {
    const binding = reviewBinding(value), existing = snapshots.get(binding)
    if (existing && existing.version >= value.version) return existing
    const snapshot = { ...value, items: Object.fromEntries(Object.entries(value.items).map(([key, item]) => [key, { ...item }])) }
    snapshots.set(binding, snapshot)
    return snapshot
  }
  const sameDraft = (first: { status: ReviewStatus; note: string }, second: { status: ReviewStatus; note: string } | undefined) =>
    !!second && first.status === second.status && first.note === second.note
  watch(() => evidence.value ? snapshots.get(reviewBinding(evidence.value)) : undefined, value => {
    if (!value || !evidence.value || !reviews.value || value.version <= reviews.value.version) return
    reviews.value = value
    const persisted = value.items[evidence.value.issue_key]
    if (draftChanged && sameDraft(draft, persisted)) {
      const key = cacheKey(evidence.value), pending = draftCache.get(key)
      if (pending && sameDraft(pending, persisted)) draftCache.delete(key)
      draftChanged = false; unsaved.value = false; restoredDraft.value = false; saved.value = true
    } else if (!draftChanged) restoreReview()
  }, { flush: 'sync' })

  async function openIssue(selected: number) {
    if (!eligible.value || !job.value || !Number.isInteger(selected) || selected < 0 || selected >= (job.value.result?.issues?.length || 0)) return
    rememberDraft()
    const id = job.value.id, g = generation, sequence = ++evidenceSequence
    reviewSequence++; refreshingReviews.value = false
    index.value = selected; evidence.value = null; reviews.value = null; loading.value = true; error.value = ''; reviewError.value = ''; saved.value = false
    applyDraft(); draftChanged = false; unsaved.value = false; restoredDraft.value = false
    const tasks = await Promise.allSettled([client.issueEvidence(id, selected), client.jobReviews(id)])
    if (!current(g, id) || sequence !== evidenceSequence) return
    const [issueResult, reviewsResult] = tasks
    if (issueResult.status === 'fulfilled') {
      const value = issueResult.value
      if (value.job_id !== id || value.issue_index !== selected || value.input_sha256 !== job.value?.result?.input_sha256 || value.profile_sha256 !== job.value?.result?.profile_sha256) error.value = '定位证据与当前问题不一致，请重新读取。'
      else evidence.value = value
    } else error.value = message(issueResult.reason)
    if (reviewsResult.status === 'fulfilled') {
      try {
        checkReviews(reviewsResult.value, id); reviews.value = rememberReviews(reviewsResult.value)
        restoreReview()
      } catch (value) { reviewError.value = message(value) }
    } else reviewError.value = message(reviewsResult.reason)
    if (evidence.value && !reviews.value) {
      const cached = draftCache.get(cacheKey(evidence.value))
      if (cached && !draftChanged) {
        applyDraft(cached.status, cached.note); draftChanged = true; unsaved.value = true; restoredDraft.value = true
      }
    }
    rememberDraft()
    loading.value = false
  }

  function closeIssue() { rememberDraft(); index.value = null; evidenceSequence++; loading.value = false }

  function discardDraft() {
    if (saving.value || !evidence.value || !reviews.value) return
    draftCache.delete(cacheKey(evidence.value))
    const existing = reviews.value.items[evidence.value.issue_key]
    applyDraft(existing?.status, existing?.note)
    draftChanged = false; unsaved.value = false; restoredDraft.value = false; saved.value = false
  }

  async function refreshReviews() {
    if (!job.value || !evidence.value || loading.value || refreshingReviews.value || saving.value) return
    const id = job.value.id, g = generation, sequence = ++reviewSequence
    refreshingReviews.value = true; reviewError.value = ''; reviews.value = null
    try {
      const value = await client.jobReviews(id)
      if (!current(g, id) || sequence !== reviewSequence) return
      checkReviews(value, id); reviews.value = rememberReviews(value)
      restoreReview()
      // Preserve the user's typed note when resolving an optimistic conflict.
    } catch (value) { if (current(g, id) && sequence === reviewSequence) reviewError.value = message(value) }
    finally { if (current(g, id) && sequence === reviewSequence) refreshingReviews.value = false }
  }

  async function saveReview() {
    if (!canSaveReview.value || !job.value || !evidence.value || !reviews.value) return
    const id = job.value.id, g = generation, sequence = evidenceSequence, key = evidence.value.issue_key
    const binding = evidence.value, cachedKey = cacheKey(binding)
    const submitted = { status: draft.status, note: draft.note }
    saving.value = true; reviewError.value = ''; saved.value = false
    try {
      const response = await client.saveJobReview(id, { version: reviews.value.version, issue_key: key,
        ...submitted, input_sha256: evidence.value.input_sha256, profile_sha256: evidence.value.profile_sha256 })
      if (response.job_id !== id || response.input_sha256 !== binding.input_sha256 || response.profile_sha256 !== binding.profile_sha256) throw Error('复核记录与提交的报告不一致。')
      const value = rememberReviews(response)
      const persisted = value.version > response.version ? value.items[key] : submitted
      const pending = draftCache.get(cachedKey)
      if (pending && sameDraft(pending, persisted)) draftCache.delete(cachedKey)
      if (!current(g, id) || sequence !== evidenceSequence) {
        if (evidence.value && cacheKey(evidence.value) === cachedKey && sameDraft(draft, persisted)) {
          draftChanged = false; unsaved.value = false; restoredDraft.value = false
          if (current(g, id)) { reviews.value = value; saved.value = true }
        }
        return
      }
      checkReviews(value, id); reviews.value = value
      draftChanged = !sameDraft(draft, persisted)
      unsaved.value = draftChanged; restoredDraft.value = false
      rememberDraft()
      saved.value = !draftChanged
    } catch (value) { if (current(g, id) && sequence === evidenceSequence) reviewError.value = message(value) }
    finally { if (current(g, id)) saving.value = false }
  }

  async function loadComparison() {
    if (!job.value || !eligible.value || comparing.value) return
    const id = job.value.id, g = generation, sequence = ++compareSequence
    comparing.value = true; compareError.value = ''
    try {
      const value = await client.jobComparison(id)
      if (!current(g, id) || sequence !== compareSequence) return
      if (value.job_id && value.job_id !== id) throw Error('复检对照与当前任务不一致。')
      comparison.value = value
    } catch (value) { if (current(g, id) && sequence === compareSequence) compareError.value = message(value) }
    finally { if (current(g, id) && sequence === compareSequence) comparing.value = false }
  }
  onUnmounted(() => { rememberDraft(); disposed = true; generation++ })
  return { index, evidence, reviews, comparison, eligible, canSaveReview, loading, saving, comparing, refreshingReviews,
    error, reviewError, compareError, draft, saved, unsaved, restoredDraft, openIssue, closeIssue, discardDraft, refreshReviews, saveReview, loadComparison }
}
