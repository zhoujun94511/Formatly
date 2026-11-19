import { computed, onUnmounted, ref } from 'vue'
import { api } from '../api'
import type { Profile, Requirement, School, WorkspaceWarning } from '../types'

export function useSchoolWorkspace() {
  const items = ref<School[]>([]), selected = ref<School | null>(null)
  const schoolWarnings = ref<WorkspaceWarning[]>([])
  const generatedProfiles = ref<Profile[]>([])
  const listLoading = ref(false), detailLoading = ref(false), saving = ref(false), notice = ref('')
  const listError = ref(''), detailError = ref(''), saveError = ref('')
  const loading = computed(() => listLoading.value || detailLoading.value)
  const error = computed(() => saveError.value || detailError.value || listError.value)
  let disposed = false, revision = 0, listRevision = 0, mutation = 0
  const message = (value: unknown) => value instanceof Error ? value.message : String(value)
  function upsert(school: School) { mutation += 1; items.value = [school, ...items.value.filter(item => item.id !== school.id)] }
  async function refresh() {
    const request = ++listRevision, before = mutation
    listLoading.value = true; listError.value = ''
    try {
      const result = await api.schools()
      if (!disposed && request === listRevision) {
        schoolWarnings.value = result.warnings || []
        const local = new Set(items.value.map(item => item.id))
        items.value = before === mutation ? result.items : [...items.value, ...result.items.filter(item => !local.has(item.id))]
      }
    } catch (value) { if (!disposed && request === listRevision && before === mutation) listError.value = message(value) }
    finally { if (!disposed && request === listRevision) listLoading.value = false }
  }
  async function select(id: string) {
    const request = ++revision
    selected.value = null; generatedProfiles.value = []; detailError.value = ''; saveError.value = ''; notice.value = ''
    if (!id) { detailLoading.value = false; return }
    detailLoading.value = true
    try { const result = await api.school(id); if (!disposed && request === revision) { selected.value = result; upsert(result) } }
    catch (value) { if (!disposed && request === revision) detailError.value = message(value) }
    finally { if (!disposed && request === revision) detailLoading.value = false }
  }
  async function create(name: string) {
    if (saving.value) return
    saving.value = true; saveError.value = ''
    try { const result = await api.createSchool(name); if (!disposed) { upsert(result); return result } }
    catch (value) { if (!disposed) saveError.value = message(value) }
    finally { if (!disposed) saving.value = false }
  }
  async function addSource(body: FormData, schoolName = '') {
    if (saving.value || (!selected.value && !schoolName.trim())) return false
    const request = revision
    saving.value = true; saveError.value = ''; notice.value = ''
    try {
      if (!selected.value) {
        const school = await api.createSchool(schoolName.trim())
        if (disposed || request !== revision) return false
        selected.value = school; upsert(school)
      }
      const id = selected.value.id
      const result = await api.addSchoolSource(id, body)
      if (!disposed && request === revision) { selected.value = result; generatedProfiles.value = []; upsert(result); notice.value = '候选要求尚未自动启用，请核对后生成方案。'; return true }
    } catch (value) { if (!disposed && request === revision) saveError.value = message(value) }
    finally { if (!disposed) saving.value = false }
    return false
  }
  async function confirm(requirements: Requirement[], expectedVersion = selected.value?.version) {
    if (saving.value || !selected.value) return false
    const id = selected.value.id, request = revision
    saving.value = true; saveError.value = ''; notice.value = ''
    try {
      const result = await api.confirmSchool(id, requirements, expectedVersion)
      if (!disposed && request === revision) { selected.value = result.school; generatedProfiles.value = result.profiles; upsert(result.school); notice.value = `已生成 ${result.profiles.length} 个规则方案。`; return true }
    } catch (value) { if (!disposed && request === revision) saveError.value = message(value) }
    finally { if (!disposed) saving.value = false }
    return false
  }
  onUnmounted(() => { disposed = true; revision += 1; listRevision += 1 })
  return { items, selected, schoolWarnings, generatedProfiles, loading, saving, error, notice, refresh, select, create, addSource, confirm }
}
