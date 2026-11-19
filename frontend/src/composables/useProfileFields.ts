import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import type { ProfileFields } from '../utils/profileFields'

export function useProfileFields() {
  const metadata = ref<ProfileFields | null>(null), loading = ref(false), error = ref('')
  let request = 0, disposed = false
  async function load() {
    const current = ++request
    loading.value = true; error.value = ''
    try { const result = await api.profileFields(); if (!disposed && current === request) metadata.value = result }
    catch (value) { if (!disposed && current === request) error.value = value instanceof Error ? value.message : String(value) }
    finally { if (!disposed && current === request) loading.value = false }
  }
  onMounted(load)
  onUnmounted(() => { disposed = true; request += 1 })
  return { metadata, loading, error, load }
}
