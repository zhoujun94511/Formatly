import { onUnmounted, shallowRef, type Ref } from 'vue'
import type { Job } from '../types'
import type { AuditDraft } from './useAuditDraft'
import type { useAuditStore } from './useAuditStore'

interface ActionsContext {
  routeVersion: Ref<number>
  route: () => string
  selectedId: Ref<string>
  draft: AuditDraft
  store: Pick<ReturnType<typeof useAuditStore>, 'createJob' | 'retry' | 'error'>
  navigate: (route: string) => void
}

export function useSingleAuditActions({ routeVersion, route, selectedId, draft, store, navigate }: ActionsContext) {
  const backgroundJob = shallowRef<Job | null>(null)
  let disposed = false
  function routeGuard() {
    const version = routeVersion.value, origin = route()
    return () => !disposed && version === routeVersion.value && origin === route()
  }
  async function submit(form: FormData) {
    if (disposed) return
    const currentRoute = routeGuard(), version = draft.version.value
    if (draft.revisionOf.value) form.set('revision_of_job_id', draft.revisionOf.value)
    try {
      const job = await store.createJob(form)
      if (!job || disposed) return
      if (currentRoute() && version === draft.version.value) { draft.clearFiles(); navigate(`job/${job.id}`) }
      else backgroundJob.value = job
    } catch (value) { if (!disposed) store.error.value = value instanceof Error ? value.message : String(value) }
  }
  async function retry() {
    if (disposed) return
    const id = selectedId.value, currentRoute = routeGuard()
    if (!id) return
    try {
      const job = await store.retry(id)
      if (!job || disposed) return
      if (currentRoute() && selectedId.value === id) navigate(`job/${job.id}`)
      else backgroundJob.value = job
    } catch (value) { if (!disposed) store.error.value = value instanceof Error ? value.message : String(value) }
  }
  onUnmounted(() => { disposed = true })
  return { submit, retry, backgroundJob }
}
