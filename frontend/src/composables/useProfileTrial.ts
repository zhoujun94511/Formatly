import { onUnmounted, ref, shallowRef } from 'vue'
import { api } from '../api'
import type { Profile } from '../types'

export const backgroundTrialJobId = shallowRef<string | null>(null)
export const backgroundTrialError = shallowRef<string | null>(null)

export function useProfileTrial() {
  const busyId = ref(''), error = ref('')
  let disposed = false
  onUnmounted(() => { disposed = true })
  async function run(profile: Profile) {
    if (busyId.value) return null
    busyId.value = profile.id; error.value = ''
    try {
      const job = await api.trialProfile(profile.id, profile.kinds?.[0] || 'thesis')
      if (disposed) { backgroundTrialJobId.value = job.id; return null }
      return job.id
    } catch (value) {
      const text = value instanceof Error ? value.message : String(value)
      if (disposed) backgroundTrialError.value = text
      else error.value = text
      return null
    } finally { if (!disposed) busyId.value = '' }
  }
  return { busyId, error, run }
}
