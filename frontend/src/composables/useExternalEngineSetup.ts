import { computed, onUnmounted, ref, watch, type Ref } from 'vue'
import { api } from '../api'
import type { ExternalEngineStatus, Preflight } from '../types'

export function useExternalEngineSetup(engine: Readonly<Ref<ExternalEngineStatus | undefined>>, refreshing: Readonly<Ref<boolean>>, client = api) {
  const kind = ref<'thesis' | 'intern'>('thesis')
  const preflight = ref<Preflight | null>(null), checking = ref(false), error = ref('')
  let revision = 0, disposed = false
  const canCheck = computed(() => !refreshing.value && engine.value?.available === true && engine.value.kinds.includes(kind.value))
  const ready = computed(() => canCheck.value && !checking.value && preflight.value?.available === true)

  function invalidate() {
    revision += 1
    preflight.value = null; checking.value = false; error.value = ''
  }
  async function check() {
    const current = engine.value
    if (!canCheck.value || !current || checking.value || disposed) return
    const request = ++revision, profileId = current.profile_id, documentKind = kind.value
    preflight.value = null; error.value = ''; checking.value = true
    try {
      const result = await client.preflight(profileId, documentKind, 'docx')
      if (!disposed && request === revision) preflight.value = result
    } catch (value) {
      if (!disposed && request === revision) error.value = value instanceof Error ? value.message : String(value)
    } finally {
      if (!disposed && request === revision) checking.value = false
    }
  }
  watch([engine, refreshing, kind], invalidate, { flush: 'sync', deep: true })
  onUnmounted(() => { disposed = true; invalidate() })
  return { kind, preflight, checking, error, canCheck, ready, check }
}
