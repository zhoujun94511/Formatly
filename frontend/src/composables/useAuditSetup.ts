import { computed, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import { api } from '../api'
import type { DocumentFormat, MaterialCollection, Preflight, WorkspaceWarning } from '../types'

export function useAuditSetup(profileId: Ref<string>, kind: Ref<string>, format: Readonly<Ref<DocumentFormat>> = ref<DocumentFormat>('docx'), ruleSignature: Readonly<Ref<string>> = profileId) {
  const preflight = ref<Preflight | null>(null), checking = ref(false), error = ref('')
  const collections = ref<MaterialCollection[]>([]), collectionError = ref('')
  const collectionWarnings = ref<WorkspaceWarning[]>([])
  const ready = computed(() => !checking.value && preflight.value?.available === true)
  let revision = 0, collectionsRevision = 0, disposed = false
  const message = (value: unknown) => value instanceof Error ? value.message : String(value)
  async function check() {
    const request = ++revision, id = profileId.value, documentKind = kind.value, inputFormat = format.value
    preflight.value = null; error.value = ''
    if (!id || !ruleSignature.value) { checking.value = false; return }
    checking.value = true
    try { const value = await api.preflight(id, documentKind, inputFormat); if (!disposed && request === revision) preflight.value = value }
    catch (value) { if (!disposed && request === revision) error.value = message(value) }
    finally { if (!disposed && request === revision) checking.value = false }
  }
  async function loadCollections() {
    const request = ++collectionsRevision
    collectionError.value = ''
    try {
      const data = await api.collections()
      if (!disposed && request === collectionsRevision) { collections.value = data.items; collectionWarnings.value = data.warnings || [] }
    }
    catch (value) { if (!disposed && request === collectionsRevision) collectionError.value = message(value) }
  }
  watch([profileId, kind, format, ruleSignature], check, { immediate: true, flush: 'sync' })
  onMounted(loadCollections)
  onUnmounted(() => { disposed = true; revision += 1; collectionsRevision += 1 })
  return { preflight, checking, ready, error, check, collections, collectionError, collectionWarnings, loadCollections }
}
