import { computed, onUnmounted, ref, shallowRef, watch, type MaybeRefOrGetter, toValue } from 'vue'
import { api } from '../api'
import type { Job, RepairPlan } from '../types'

export const backgroundRepairJob = shallowRef<Job | null>(null)
export const backgroundRepairError = shallowRef<string | null>(null)

export function supportsRepairFormat(job: Job | null) {
  const format = job?.result?.input_format
  return !format || format === 'docx'
}

export function useDocumentRepair(source: MaybeRefOrGetter<Job | null>, client: Pick<typeof api, 'repairPlan' | 'applyRepairs'> = api) {
  const plan = ref<RepairPlan | null>(null)
  const selectedIds = ref<string[]>([])
  const loading = ref(false), saving = ref(false), error = ref('')
  const createdJob = ref<Job | null>(null)
  let disposed = false, revision = 0
  const job = computed(() => toValue(source))
  const eligible = computed(() => job.value?.status === 'completed' && !!job.value.result && job.value.result.status !== 'incomplete' && supportsRepairFormat(job.value))
  const canSubmit = computed(() => eligible.value && !!plan.value?.available && selectedIds.value.length > 0 && !loading.value && !saving.value && !createdJob.value)
  const message = (value: unknown) => value instanceof Error ? value.message : String(value)

  watch([() => job.value?.id, () => job.value?.status, () => job.value?.result?.input_sha256, () => job.value?.result?.profile_sha256, () => job.value?.result?.input_format], () => {
    revision += 1
    plan.value = null; selectedIds.value = []; error.value = ''; createdJob.value = null
    loading.value = false; saving.value = false
  }, { flush: 'sync' })

  function current(request: number, id: string) {
    return !disposed && request === revision && job.value?.id === id
  }

  async function preview() {
    if (disposed || loading.value || saving.value || createdJob.value || !eligible.value || !job.value) return
    const id = job.value.id, request = ++revision
    loading.value = true; error.value = ''; plan.value = null; selectedIds.value = []; createdJob.value = null
    try {
      const result = await client.repairPlan(id)
      if (!current(request, id)) return
      if (result.job_id !== id) throw Error('修复预览与当前检测不匹配，请重新读取。')
      plan.value = result
    } catch (value) { if (current(request, id)) error.value = message(value) }
    finally { if (current(request, id)) loading.value = false }
  }

  async function apply() {
    if (disposed || !canSubmit.value || !job.value || !plan.value) return
    const id = job.value.id, request = revision, planId = plan.value.plan_id
    const chosen = [...new Set(selectedIds.value)]
    const candidates = new Set(plan.value.candidates.map(candidate => candidate.id))
    if (chosen.length !== selectedIds.value.length || chosen.some(candidate => !candidates.has(candidate))) {
      error.value = '所选项目已失效，请重新读取修复预览。'
      return
    }
    saving.value = true; error.value = ''
    try {
      const result = await client.applyRepairs(id, planId, chosen)
      if (!current(request, id)) { backgroundRepairJob.value = result; return }
      createdJob.value = result
      return result
    } catch (value) {
      const text = message(value)
      if (current(request, id)) error.value = text
      else backgroundRepairError.value = text
    }
    finally { if (current(request, id)) saving.value = false }
  }

  onUnmounted(() => { disposed = true; revision += 1 })
  return { plan, selectedIds, loading, saving, error, eligible, canSubmit, createdJob, preview, apply }
}
