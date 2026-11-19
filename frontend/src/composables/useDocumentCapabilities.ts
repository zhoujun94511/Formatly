import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import type { Capabilities } from '../types'

export function useDocumentCapabilities() {
  const capabilities = ref<Capabilities | null>(null), loading = ref(false), error = ref('')
  let disposed = false, revision = 0
  async function refresh() {
    const request = ++revision
    loading.value = true; error.value = ''
    try { const result = await api.capabilities(); if (!disposed && request === revision) capabilities.value = result }
    catch (value) { if (!disposed && request === revision) error.value = value instanceof Error ? value.message : String(value) }
    finally { if (!disposed && request === revision) loading.value = false }
  }
  onMounted(refresh)
  onUnmounted(() => { disposed = true; revision += 1 })
  return { capabilities, loading, error, refresh }
}
