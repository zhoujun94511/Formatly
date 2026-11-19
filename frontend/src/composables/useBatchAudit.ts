import { computed, onUnmounted, ref, shallowRef, watch, type Ref } from 'vue'
import { api } from '../api'
import type { Batch, DocumentFormat, Preflight, Profile } from '../types'
import { documentFormat, maxDocumentBytes } from '../utils/documents'
import { profileRuleSignature } from '../utils/profileSignature'
import { useDocumentScope, type DocumentScopeApi } from './useDocumentScope'

const message = (value: unknown) => value instanceof Error ? value.message : String(value)
const batchKey = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, '0')).join('')
export const backgroundBatchId = shallowRef<string | null>(null)
export const backgroundBatchError = shallowRef<string | null>(null)
type BatchApi = Pick<typeof api, 'preflight' | 'batch' | 'createBatch' | 'cancelJob' | 'retry'> & DocumentScopeApi
export function useBatchAudit(profiles: Ref<Profile[]>, selectedId: Ref<string | undefined>, backend: BatchApi = api) {
  const files = ref<File[]>([]), profileId = ref(''), kind = ref('thesis'), error = ref(''), fileError = ref('')
  const busy = ref(false), loading = ref(false), checking = ref(false), preflightFailed = ref(false), batch = ref<Batch | null>(null)
  const preflights = ref<Partial<Record<DocumentFormat, Preflight>>>({})
  const actionId = ref(''), key = ref(batchKey())
  let generation = 0, inputGeneration = 0, viewGeneration = 0, submitGeneration = 0, actionGeneration = 0
  let poll: ReturnType<typeof window.setTimeout> | undefined, disposed = false
  let pendingLoad: { id: string; generation: number; promise: Promise<void> } | undefined
  let pendingPreflight: { generation: number; promise: Promise<void> } | undefined
  const pendingSubmission = ref<{ configuration: number; form: FormData } | null>(null)
  const selectedProfile = computed(() => profiles.value.find(profile => profile.id === profileId.value))
  const ruleSignature = computed(() => profileRuleSignature(selectedProfile.value))
  // Slots keep each file's review alive while another file is being edited.
  // Replacing a file invalidates only that slot, including same-name changes.
  const scopeIndex = ref(0), scopeSlotOrder = ref<number[]>([])
  const scopeFiles = Array.from({ length: 20 }, () => ref<File | null>(null))
  const scopeWorkspaces = scopeFiles.map(file => useDocumentScope(file, profileId, kind, ruleSignature,
    computed(() => file.value ? preflights.value[documentFormat(file.value.name) as DocumentFormat] || null : null), backend))
  const documentScopes = computed(() => scopeSlotOrder.value.map(slot => scopeWorkspaces[slot]!))
  const scopeSlot = computed(() => scopeSlotOrder.value[scopeIndex.value])
  const documentScope = computed(() => documentScopes.value[scopeIndex.value])
  const scopeReviews = computed(() => files.value.map((file, index) => {
    const scope = documentScopes.value[index]!
    return { index, name: file.name, needsScope: scope.needsScope.value, ready: scope.ready.value,
      started: scope.started.value, complete: scope.complete.value, completed: scope.completed.value, total: scope.requirements.value.length }
  }).filter(item => item.needsScope))
  const scopesReady = computed(() => documentScopes.value.every(scope => scope.ready.value))
  // Automatic expiry changes validity, but does not change an already-sent intent.
  const scopeIntentSignature = computed(() => documentScopes.value.map(scope => scope.intentVersion.value).join(','))
  watch(scopeReviews, items => {
    if (!items.some(item => item.index === scopeIndex.value)) scopeIndex.value = items[0]?.index || 0
  }, { flush: 'sync' })
  const formats = computed(() => [...new Set(files.value.map(file => documentFormat(file.name)).filter(Boolean))] as DocumentFormat[])
  const running = computed(() => batch.value?.items.some(item => ['queued', 'running'].includes(item.job?.status || '')) ?? false)
  const canSubmit = computed(() => !selectedId.value && !!files.value.length && !!selectedProfile.value && !busy.value && !checking.value && !preflightFailed.value && !fileError.value
    && formats.value.length > 0 && formats.value.every(format => preflights.value[format]?.available) && scopesReady.value)
  const canRecoverSubmission = computed(() => !selectedId.value && !busy.value && !checking.value && !fileError.value
    && pendingSubmission.value?.configuration === inputGeneration)
  watch(profiles, values => { if (!profileId.value) profileId.value = values.find(item => item.id === 'generic')?.id || values[0]?.id || '' }, { immediate: true })
  // A transport timeout keeps the same key. Only changing the actual submission
  // inputs creates another intent; a background list refresh must not do so.
  watch([files, profileId, kind, ruleSignature, scopeIntentSignature], () => {
    inputGeneration += 1; key.value = batchKey(); pendingSubmission.value = null
  }, { flush: 'sync' })
  function check(): Promise<void> {
    if (disposed) return Promise.resolve()
    const request = generation
    if (pendingPreflight?.generation === request) return pendingPreflight.promise
    const id = profileId.value, documentKind = kind.value, inputFormats = [...formats.value]
    if (!files.value.length || !id) { checking.value = false; return Promise.resolve() }
    checking.value = true; preflightFailed.value = false; error.value = ''
    const promise = (async () => {
      try {
        const results = await Promise.all(inputFormats.map(async format => [format, await backend.preflight(id, documentKind, format)] as const))
        if (!disposed && request === generation) preflights.value = Object.fromEntries(results)
      } catch (value) {
        if (request === generation && !disposed) { preflightFailed.value = true; error.value = message(value) }
      } finally {
        if (request === generation && !disposed) { checking.value = false; pendingPreflight = undefined }
      }
    })()
    pendingPreflight = { generation: request, promise }
    return promise
  }
  watch([files, profileId, kind, ruleSignature], () => {
    generation++; pendingPreflight = undefined; preflights.value = {}; preflightFailed.value = false; error.value = ''
    void check()
  }, { flush: 'sync' })
  function choose(chosen: File[]) {
    if (disposed || busy.value) return
    fileError.value = ''
    if (chosen.length > 20) { fileError.value = '每批最多20份原稿。'; return }
    const invalid = chosen.find(file => !documentFormat(file.name) || !file.size || file.size > maxDocumentBytes)
    if (invalid) { fileError.value = `${invalid.name}：请选择非空的 DOCX、PDF、TXT、MD 或 JSON，单份不超过40 MB。`; return }
    if (chosen.reduce((sum, file) => sum + file.size, 0) > 80 * 1024 * 1024) { fileError.value = '每批原稿合计不能超过80 MB。'; return }
    replaceFiles(chosen)
  }
  function replaceFiles(chosen: File[]) {
    const previous = scopeSlotOrder.value.map((slot, index) => ({ slot, file: files.value[index] }))
    const activeSlot = scopeSlotOrder.value[scopeIndex.value], used = new Set<number>()
    const order = chosen.map(file => {
      const existing = previous.find(item => item.file === file && !used.has(item.slot))
      if (!existing) return -1
      used.add(existing.slot); return existing.slot
    }).map(slot => {
      if (slot !== -1) return slot
      const available = scopeFiles.findIndex((_file, index) => !used.has(index))
      used.add(available); return available
    })
    scopeFiles.forEach((file, slot) => { const index = order.indexOf(slot); file.value = index < 0 ? null : chosen[index]! })
    // Update both together: consumers must never pair a new file with old bindings.
    files.value = []; scopeSlotOrder.value = order; files.value = [...chosen]
    scopeIndex.value = Math.max(0, order.indexOf(activeSlot ?? -1))
  }
  function clearPoll() { if (poll !== undefined) window.clearTimeout(poll); poll = undefined }
  function activeBatchId() { return selectedId.value || batch.value?.batch_id }
  function schedule() {
    clearPoll()
    if (!disposed && running.value) poll = window.setTimeout(() => { poll = undefined; void load() }, 1800)
  }
  function load(): Promise<void> {
    const id = activeBatchId(), request = viewGeneration
    if (!id || disposed) return Promise.resolve()
    if (pendingLoad?.id === id && pendingLoad.generation === request) return pendingLoad.promise
    clearPoll()
    loading.value = true; error.value = ''
    const current = () => !disposed && request === viewGeneration && activeBatchId() === id
    const promise = Promise.resolve().then(async () => {
      try {
        const result = await backend.batch(id)
        if (!current()) return
        if (result.batch_id !== id) throw new Error('批次响应与当前请求不一致，请重新读取。')
        batch.value = result
      } catch (value) { if (current()) error.value = message(value) }
      finally {
        if (current()) { pendingLoad = undefined; loading.value = false; schedule() }
      }
    })
    pendingLoad = { id, generation: request, promise }
    return promise
  }
  watch(selectedId, () => {
    viewGeneration += 1; submitGeneration += 1; actionGeneration += 1
    pendingSubmission.value = null
    clearPoll(); pendingLoad = undefined
    batch.value = null; error.value = ''; loading.value = false; busy.value = false; actionId.value = ''
    if (selectedId.value) void load()
  }, { immediate: true, flush: 'sync' })
  async function submit() {
    if (disposed || !canSubmit.value) return null
    if (pendingSubmission.value?.configuration === inputGeneration) return send(pendingSubmission.value)
    const form = new FormData()
    form.set('profile_id', profileId.value); form.set('kind', kind.value); form.set('batch_key', key.value)
    files.value.forEach((file, index) => form.set(`document${index}`, file))
    const scopeBindings = documentScopes.value.map(scope => scope.payload())
    if (scopeBindings.some(Boolean)) form.set('scope_bindings', JSON.stringify(scopeBindings))
    const submission = { configuration: inputGeneration, form }
    pendingSubmission.value = submission
    return send(submission)
  }
  async function recoverSubmission() {
    if (disposed || !canRecoverSubmission.value || !pendingSubmission.value) return null
    return send(pendingSubmission.value)
  }
  async function send(submission: { configuration: number; form: FormData }) {
    const request = ++submitGeneration, view = viewGeneration
    busy.value = true; error.value = ''
    const inView = () => !disposed && request === submitGeneration && view === viewGeneration
    const current = () => inView() && submission.configuration === inputGeneration
    try {
    const result = await backend.createBatch(submission.form)
    if (!current()) { backgroundBatchId.value = result.batch_id; return null }
    pendingSubmission.value = null
      batch.value = result; replaceFiles([]); schedule(); return result.batch_id
    } catch (value) {
      const text = message(value)
      if (current()) error.value = text
      else backgroundBatchError.value = text
      return null
    }
    finally { if (inView()) busy.value = false }
  }
  async function cancel(id: string) {
    if (disposed || actionId.value) return
    const request = ++actionGeneration, view = viewGeneration
    const current = () => !disposed && request === actionGeneration && view === viewGeneration
    actionId.value = id; error.value = ''
    try { await backend.cancelJob(id); if (current()) await load() } catch (value) { if (current()) error.value = message(value) }
    finally { if (current()) actionId.value = '' }
  }
  async function retry(id: string) {
    if (disposed || actionId.value) return null
    const request = ++actionGeneration, view = viewGeneration
    const current = () => !disposed && request === actionGeneration && view === viewGeneration
    actionId.value = id; error.value = ''
    try { const result = await backend.retry(id); return current() ? result.id : null }
    catch (value) { if (current()) error.value = message(value); return null }
    finally { if (current()) actionId.value = '' }
  }
  onUnmounted(() => { disposed = true; generation += 1; viewGeneration += 1; submitGeneration += 1; actionGeneration += 1; clearPoll(); pendingLoad = undefined; pendingPreflight = undefined; pendingSubmission.value = null })
  return { files, profileId, kind, error, fileError, busy, loading, checking, preflightFailed, batch, preflights, actionId, canSubmit, canRecoverSubmission,
    scopeIndex, scopeSlot, scopeReviews, documentScope, documentScopes, scopesReady, choose, submit, recoverSubmission, check, load, cancel, retry }
}
