import { computed, onUnmounted, ref } from 'vue'
import { api } from '../api'
import type { MaterialCollection, WorkspaceWarning } from '../types'

export function useCollectionWorkspace() {
  const items = ref<MaterialCollection[]>([]), selected = ref<MaterialCollection | null>(null)
  const collectionWarnings = ref<WorkspaceWarning[]>([])
  const listLoading = ref(false), detailLoading = ref(false), saving = ref(false)
  const listError = ref(''), detailError = ref(''), saveError = ref('')
  const loading = computed(() => listLoading.value || detailLoading.value)
  const error = computed(() => saveError.value || detailError.value || listError.value)
  let disposed = false, revision = 0, listRevision = 0, mutation = 0, timer: ReturnType<typeof window.setTimeout> | undefined
  const message = (value: unknown) => value instanceof Error ? value.message : String(value)
  async function refresh() {
    const request = ++listRevision, before = mutation
    listError.value = ''; listLoading.value = true
    try {
      const value = await api.collections()
      if (!disposed && request === listRevision) {
        collectionWarnings.value = value.warnings || []
        const local = new Set(items.value.map(item => item.id))
        items.value = before === mutation ? value.items : [...items.value, ...value.items.filter(item => !local.has(item.id))]
      }
    } catch (value) { if (!disposed && request === listRevision && before === mutation) listError.value = message(value) }
    finally { if (!disposed && request === listRevision) listLoading.value = false }
  }
  async function select(id: string, silent = false) {
    window.clearTimeout(timer)
    const request = ++revision
    detailError.value = ''; saveError.value = ''
    if (!silent) { if (selected.value?.id !== id) selected.value = null; detailLoading.value = true }
    if (!id) { selected.value = null; detailLoading.value = false; return }
    try {
      const value = await api.collection(id)
      if (disposed || request !== revision) return
      selected.value = value
      if (value.items?.some(job => job.status === 'running' || job.status === 'queued')) timer = window.setTimeout(() => { void select(id, true) }, 1800)
    } catch (value) {
      if (!disposed && request === revision) {
        detailError.value = message(value)
        if (silent) timer = window.setTimeout(() => { void select(id, true) }, 3000)
      }
    } finally { if (!disposed && request === revision) detailLoading.value = false }
  }
  async function create(name: string, kinds: string[]) {
    if (saving.value) return
    saveError.value = ''; saving.value = true
    try { const value = await api.createCollection(name, kinds); if (!disposed) { mutation += 1; items.value = [value, ...items.value.filter(item => item.id !== value.id)]; return value } }
    catch (value) { if (!disposed) saveError.value = message(value) }
    finally { if (!disposed) saving.value = false }
  }
  onUnmounted(() => { disposed = true; revision += 1; listRevision += 1; window.clearTimeout(timer) })
  return { items, selected, collectionWarnings, loading, saving, error, refresh, select, create }
}
