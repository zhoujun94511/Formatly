import { computed, ref, watch, type Ref } from 'vue'

export function usePagedItems<T>(items: Ref<T[]>, pageSize = 10, resetOnReplace = true) {
  const page = ref(1)
  const pageCount = computed(() => Math.max(1, Math.ceil(items.value.length / pageSize)))
  watch(items, () => { page.value = resetOnReplace ? 1 : Math.min(page.value, pageCount.value) }, { flush: 'sync' })
  function setPage(value: number) {
    page.value = Math.min(pageCount.value, Math.max(1, Number.isFinite(value) ? Math.trunc(value) : 1))
  }
  const displayed = computed(() => items.value.slice((page.value - 1) * pageSize, page.value * pageSize))
  return { page, pageCount, displayed, setPage }
}
