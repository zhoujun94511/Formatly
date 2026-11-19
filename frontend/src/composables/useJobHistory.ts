import { computed, onUnmounted, ref, watch, type Ref } from 'vue'
import { api } from '../api'
import type { Job } from '../types'

export function useJobHistory(refreshToken: Ref<number | undefined>) {
  const query = ref(''), status = ref(''), items = ref<Job[]>([]), total = ref(0), loading = ref(false), error = ref('')
  const nextOffset = ref(0), unstable = ref(false)
  const hasMore = computed(() => !unstable.value && nextOffset.value < total.value)
  let revision = 0, disposed = false
  let timer: ReturnType<typeof window.setTimeout> | undefined
  let debounce: ReturnType<typeof window.setTimeout> | undefined
  async function load(append = false) {
    if (disposed || (append && loading.value)) return
    if (append && !hasMore.value) return
    const request = ++revision, offset = append ? nextOffset.value : 0
    const q = query.value.trim(), selectedStatus = status.value
    const pages = Math.max(1, Math.ceil((nextOffset.value + (append ? 50 : 0)) / 50))
    loading.value = true; error.value = ''; window.clearTimeout(timer); window.clearTimeout(debounce)
    try {
      const current = () => !disposed && request === revision
      const readPage = (pageOffset: number) => api.jobs({ q, status: selectedStatus, limit: 50, offset: pageOffset })
      if (append) {
        const [response, head] = await Promise.all([readPage(offset), readPage(0)])
        if (!current()) return
        const existing = new Set(items.value.map(item => item.id))
        const unique = new Set(response.items.map(item => item.id))
        const expected = Math.min(50, Math.max(0, response.total - offset))
        const sameHead = head.items.length === Math.min(50, items.value.length) && head.items.every((item, index) => item.id === items.value[index]?.id)
        if (response.total === total.value && head.total === response.total && sameHead && response.items.length === expected && unique.size === response.items.length && !response.items.some(item => existing.has(item.id))) {
          items.value = [...head.items, ...items.value.slice(head.items.length), ...response.items]; nextOffset.value = offset + response.items.length
          total.value = response.total; unstable.value = false
          return
        }
      }
      // Offset pages move when tasks are added or deleted. Read the whole loaded
      // window again, including the requested page, instead of deduplicating a
      // shifted boundary and using its shorter length as the next offset.
      for (let attempt = 0; attempt < 2; attempt += 1) {
        const responses = await Promise.all(Array.from({ length: pages }, (_, index) => readPage(index * 50)))
        if (!current()) return
        const loaded = responses.flatMap(data => data.items), count = responses[0].total
        const consistent = responses.every(data => data.total === count) && new Set(loaded.map(item => item.id)).size === loaded.length
          && loaded.length === Math.min(count, pages * 50)
        if (consistent) {
          items.value = loaded; total.value = count; nextOffset.value = loaded.length; unstable.value = false
          return
        }
      }
      unstable.value = true
      error.value = '检测记录持续变化，请刷新后继续加载。'
    } catch (e) { if (!disposed && request === revision) error.value = e instanceof Error ? e.message : String(e) }
    finally {
      if (!disposed && request === revision) {
        loading.value = false
        if (items.value.some(job => ['queued', 'running'].includes(job.status))) timer = window.setTimeout(() => void load(), 1800)
      }
    }
  }
  watch([query, status], () => {
    revision += 1; items.value = []; total.value = 0; nextOffset.value = 0; unstable.value = false; loading.value = true
    window.clearTimeout(timer); window.clearTimeout(debounce)
    debounce = window.setTimeout(() => void load(), 250)
  })
  watch(refreshToken, () => void load())
  void load()
  onUnmounted(() => { disposed = true; revision += 1; window.clearTimeout(timer); window.clearTimeout(debounce) })
  return { query, status, items, total, loading, error, hasMore, reload: () => load(), loadMore: () => load(true) }
}
