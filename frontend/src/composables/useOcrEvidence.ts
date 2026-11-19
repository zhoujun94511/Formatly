import { computed, onUnmounted, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { api } from '../api'
import type { Job } from '../types'
import type { OcrEvidence } from '../utils/reportWorkspace'

export function useOcrEvidence(source: MaybeRefOrGetter<Job | null>, client: Pick<typeof api, 'ocrEvidence'> = api) {
  const job = computed(() => toValue(source))
  const location = ref<string | null>(null), evidence = ref<OcrEvidence | null>(null)
  const loading = ref(false), error = ref('')
  let sequence = 0, disposed = false
  const extractionDigest = computed(() => {
    const engines = job.value?.result?.engines || []
    const engine = Array.isArray(engines) ? engines.find(item => item.id === 'docx-package') : engines['docx-package']
    const value = engine?.evidence
    return value && typeof value === 'object' && 'extraction_sha256' in value ? value.extraction_sha256 : undefined
  })
  const eligible = computed(() => job.value?.status === 'completed' && job.value.result?.status !== 'incomplete' && job.value.result?.input_format === 'pdf')
  function close() { sequence++; location.value = null; evidence.value = null; loading.value = false; error.value = '' }
  watch([() => job.value?.id, () => job.value?.result?.input_sha256, () => job.value?.result?.profile_sha256, extractionDigest, eligible], close, { flush: 'sync' })
  async function open(selected: string) {
    if (!eligible.value || !job.value || !job.value.result?.document_extraction?.ocr_review?.observations.some(item => item.location === selected)) return
    const id = job.value.id, current = ++sequence
    location.value = selected; evidence.value = null; error.value = ''; loading.value = true
    try {
      const value = await client.ocrEvidence(id, selected)
      if (disposed || current !== sequence) return
      const expected = job.value?.result?.document_extraction?.ocr_review?.observations.find(item => item.location === selected)
      if (!extractionDigest.value || value.extraction_sha256 !== extractionDigest.value || JSON.stringify(value.observation.bbox) !== JSON.stringify(expected?.bbox)) throw Error('原页证据与当前提取快照不一致，请重新读取。')
      if (value.job_id !== id || value.location !== selected || value.input_sha256 !== job.value?.result?.input_sha256 || value.profile_sha256 !== job.value?.result?.profile_sha256 || value.observation.location !== selected || value.observation.primary_text !== expected?.primary_text || value.observation.page !== expected?.page || value.observation.status !== expected?.status || value.observation.alternative?.text !== expected?.alternative?.text) throw Error('原页证据与当前报告不一致，请重新读取。')
      evidence.value = value
    } catch (value) { if (!disposed && current === sequence) error.value = value instanceof Error ? value.message : String(value) }
    finally { if (!disposed && current === sequence) loading.value = false }
  }
  onUnmounted(() => { disposed = true; close() })
  return { location, evidence, loading, error, eligible, open, close }
}
