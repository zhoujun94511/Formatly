import { computed, onUnmounted, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { api } from '../api'
import type { Requirement, School, SchoolSourceContext, SchoolStyleCatalog } from '../types'

type SourceSelection = Pick<Requirement, 'id' | 'source_id' | 'source_locator' | 'source_excerpt'>
const message = (value: unknown) => value instanceof Error ? value.message : String(value)

export function useSchoolSourceContext(schoolSource: MaybeRefOrGetter<School | null>, selectionSource: MaybeRefOrGetter<SourceSelection | null>,
  client: Pick<typeof api, 'schoolSourceContext'> = api) {
  const school = computed(() => toValue(schoolSource)), selection = computed(() => toValue(selectionSource))
  const selectedSource = computed(() => school.value?.sources.find(item => item.id === selection.value?.source_id))
  const context = ref<SchoolSourceContext | null>(null), loading = ref(false), error = ref('')
  let sequence = 0, disposed = false, timer: ReturnType<typeof setTimeout> | undefined
  async function load() {
    const currentSchool = school.value, selected = selection.value, request = ++sequence
    context.value = null; error.value = ''
    const source = currentSchool?.sources.find(item => item.id === selected?.source_id)
    if (!currentSchool || !selected || !source) { loading.value = false; return }
    loading.value = true
    try {
      const value = await client.schoolSourceContext(currentSchool.id, source.id, selected.source_locator, selected.source_excerpt)
      if (disposed || request !== sequence) return
      if (value.school_id !== currentSchool.id || value.source_id !== source.id || value.source_sha256 !== source.sha256
        || (source.text_sha256 && value.text_sha256 !== source.text_sha256)) throw Error('来源内容与当前要求不一致，请重新读取学校要求。')
      context.value = value
    } catch (value) { if (!disposed && request === sequence) error.value = message(value) }
    finally { if (!disposed && request === sequence) loading.value = false }
  }
  watch(() => [school.value?.id, school.value?.version, selection.value?.id, selection.value?.source_id,
    selection.value?.source_locator, selection.value?.source_excerpt, selectedSource.value?.sha256, selectedSource.value?.text_sha256], () => {
    sequence++; context.value = null; error.value = ''; loading.value = false
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => { void load() }, 180)
  }, { immediate: true })
  onUnmounted(() => { disposed = true; sequence++; if (timer) clearTimeout(timer) })
  return { context, loading, error, load }
}

export function useSchoolStyleCatalog(schoolSource: MaybeRefOrGetter<School>, sourceId: MaybeRefOrGetter<string>,
  client: Pick<typeof api, 'schoolSourceStyles'> = api) {
  const school = computed(() => toValue(schoolSource)), source = computed(() => school.value.sources.find(item => item.id === toValue(sourceId)))
  const query = ref(''), page = ref(1), catalog = ref<SchoolStyleCatalog | null>(null), loading = ref(false), error = ref('')
  let sequence = 0, disposed = false, timer: ReturnType<typeof setTimeout> | undefined
  async function load() {
    const selected = source.value, currentSchool = school.value, request = ++sequence
    catalog.value = null; error.value = ''
    if (!selected) { loading.value = false; return }
    loading.value = true
    try {
      const value = await client.schoolSourceStyles(currentSchool.id, selected.id, query.value, (page.value - 1) * 10)
      if (disposed || request !== sequence) return
      if (value.school_id !== currentSchool.id || value.source_id !== selected.id || value.source_sha256 !== selected.sha256) throw Error('样式目录与当前来源不一致，请重新读取学校要求。')
      catalog.value = value
    } catch (value) { if (!disposed && request === sequence) error.value = message(value) }
    finally { if (!disposed && request === sequence) loading.value = false }
  }
  watch([query, () => source.value?.id, () => source.value?.sha256, () => school.value.id], () => { page.value = 1 }, { flush: 'sync' })
  watch([query, page, () => source.value?.id, () => source.value?.sha256, () => school.value.id], () => {
    sequence++; catalog.value = null; error.value = ''; loading.value = false
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => { void load() }, 180)
  }, { immediate: true })
  onUnmounted(() => { disposed = true; sequence++; if (timer) clearTimeout(timer) })
  return { query, page, catalog, loading, error, load }
}
