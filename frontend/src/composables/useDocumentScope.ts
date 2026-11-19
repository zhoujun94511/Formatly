import { computed, onUnmounted, ref, watch, type Ref } from 'vue'
import { api } from '../api'
import type { DocumentPreview, DocumentScopeBindings, DocumentSectionCatalog, DocumentStyleCatalog, Preflight, ScopeBinding } from '../types'

export type DocumentScopeApi = Pick<typeof api, 'createDocumentPreview' | 'documentPreviewStyles' | 'documentPreviewSections' | 'discardDocumentPreview'>

export function useDocumentScope(file: Ref<File | null>, profileId: Ref<string>, kind: Ref<string>, signature: Readonly<Ref<string>>, preflight: Ref<Preflight | null>, client: DocumentScopeApi = api) {
  const preview = ref<DocumentPreview | null>(null), loading = ref(false), error = ref(''), expired = ref(false)
  const started = ref(false)
  const intentVersion = ref(0)
  const bindings = ref<Record<string, ScopeBinding>>({}), styleIds = ref<Record<string, string[]>>({}), sectionIndices = ref<Record<string, number[]>>({})
  const activeIndex = ref(0), query = ref(''), page = ref(1)
  const styles = ref<DocumentStyleCatalog | null>(null), sections = ref<DocumentSectionCatalog | null>(null), catalogLoading = ref(false), catalogError = ref('')
  let revision = 0, catalogRevision = 0, disposed = false, submitted = false
  let expiryTimer: ReturnType<typeof setTimeout> | undefined, searchTimer: ReturnType<typeof setTimeout> | undefined
  const needsScope = computed(() => !!preflight.value?.document_scope?.items.length)
  const required = computed(() => !!preflight.value?.document_scope?.required && preflight.value.document_scope.supported)
  const supported = computed(() => preflight.value?.document_scope?.supported === true)
  const requirements = computed(() => preview.value?.requirements || preflight.value?.document_scope?.items || [])
  const active = computed(() => requirements.value[activeIndex.value])
  const completed = computed(() => requirements.value.filter(item => bindings.value[item.id]).length)
  const complete = computed(() => !!preview.value && !expired.value && completed.value === requirements.value.length)
  const ready = computed(() => !required.value && !started.value || complete.value)
  const message = (value: unknown) => value instanceof Error ? value.message : String(value)
  function discard(id: string) { void client.discardDocumentPreview(id).catch(() => {}) }
  function invalidate() {
    intentVersion.value++
    revision++; catalogRevision++
    if (preview.value && !submitted) discard(preview.value.id)
    if (expiryTimer) clearTimeout(expiryTimer)
    if (searchTimer) clearTimeout(searchTimer)
    preview.value = null; bindings.value = {}; styleIds.value = {}; sectionIndices.value = {}
    activeIndex.value = 0; query.value = ''; page.value = 1; styles.value = null; sections.value = null
    loading.value = false; catalogLoading.value = false; error.value = ''; catalogError.value = ''; expired.value = false; submitted = false; started.value = false
  }
  async function load() {
    invalidate()
    if (!file.value || !profileId.value || !supported.value) return
    started.value = true
    const request = revision, identity = profileId.value, documentKind = kind.value
    const body = new FormData(); body.append('document', file.value); body.append('profile_id', identity); body.append('kind', documentKind)
    loading.value = true
    try {
      const result = await client.createDocumentPreview(body)
      if (disposed || request !== revision) { discard(result.id); return }
      if (result.profile_id !== identity || result.kind !== documentKind || result.input_format !== 'docx' || !result.input_sha256 || !result.profile_sha256) throw Error('原稿预览与当前检测设置不一致，请重新读取。')
      const remaining = Date.parse(result.expires_at) - Date.now()
      if (!Number.isFinite(remaining) || remaining <= 0) throw Error('原稿预览已过期，请重新读取。')
      preview.value = result
      expiryTimer = setTimeout(() => { expired.value = true; bindings.value = {}; catalogRevision++; styles.value = null; sections.value = null }, Math.min(remaining, 2147483647))
    } catch (value) { if (!disposed && request === revision) error.value = message(value) }
    finally { if (!disposed && request === revision) loading.value = false }
  }
  async function loadCatalog() {
    if (searchTimer) clearTimeout(searchTimer)
    const request = ++catalogRevision, current = preview.value, item = active.value
    styles.value = null; sections.value = null; catalogError.value = ''
    if (!current || !item || expired.value) { catalogLoading.value = false; return }
    catalogLoading.value = true
    try {
      const result = item.scope_type === 'styles' ? await client.documentPreviewStyles(current.id, query.value.trim(), (page.value - 1) * 10)
        : await client.documentPreviewSections(current.id, (page.value - 1) * 10)
      if (disposed || request !== catalogRevision || current !== preview.value) return
      if (result.input_sha256 !== current.input_sha256) { bindings.value = {}; intentVersion.value++; throw Error('原稿范围校验失败，请重新读取原稿。') }
      if (item.scope_type === 'styles') styles.value = result as DocumentStyleCatalog
      else sections.value = result as DocumentSectionCatalog
    } catch (value) { if (!disposed && request === catalogRevision) catalogError.value = message(value) }
    finally { if (!disposed && request === catalogRevision) catalogLoading.value = false }
  }
  function changeStyles(ids: string[]) { if (!active.value) return; styleIds.value[active.value.id] = [...ids]; delete bindings.value[active.value.id]; intentVersion.value++ }
  function changeSections(indices: number[]) { if (!active.value) return; sectionIndices.value[active.value.id] = [...indices]; delete bindings.value[active.value.id]; intentVersion.value++ }
  function confirm() {
    const item = active.value
    if (!item || !preview.value || expired.value || catalogLoading.value || catalogError.value) return
    if (item.scope_type === 'styles') {
      const chosen = styleIds.value[item.id] || []
      if (!chosen.length) return
      bindings.value[item.id] = { requirement_id: item.id, status: 'bound', style_ids: [...chosen] }
    } else {
      const chosen = sectionIndices.value[item.id] || []
      if (!chosen.length) return
      bindings.value[item.id] = { requirement_id: item.id, status: 'bound', section_indices: [...chosen] }
    }
    intentVersion.value++
  }
  function skip() { const item = active.value; if (item && preview.value && !expired.value) { bindings.value[item.id] = { requirement_id: item.id, status: 'unbound', reason: '暂不匹配' }; intentVersion.value++ } }
  function payload(): DocumentScopeBindings | null {
    if (!preview.value || !complete.value) return null
    return { schema_version: 1, input_sha256: preview.value.input_sha256, profile_sha256: preview.value.profile_sha256, kind: preview.value.kind,
      items: requirements.value.map(item => bindings.value[item.id]!) }
  }
  watch([file, profileId, kind, signature], invalidate, { flush: 'sync' })
  watch(activeIndex, () => { query.value = ''; page.value = 1 }, { flush: 'sync' })
  watch(query, () => { page.value = 1 }, { flush: 'sync' })
  watch([preview, activeIndex, page, query], () => {
    catalogRevision++; styles.value = null; sections.value = null; catalogError.value = ''; catalogLoading.value = !!preview.value
    if (searchTimer) clearTimeout(searchTimer)
    searchTimer = setTimeout(() => void loadCatalog(), 180)
  }, { flush: 'sync' })
  onUnmounted(() => { disposed = true; invalidate() })
  return { preview, loading, error, expired, started, intentVersion, needsScope, required, supported, requirements, active, activeIndex, query, page, styles, sections,
    catalogLoading, catalogError, bindings, styleIds, sectionIndices, completed, complete, ready, load, loadCatalog, changeStyles, changeSections, confirm, skip, payload,
    exit: invalidate, markSubmitted: () => { submitted = true } }
}
export type DocumentScopeWorkspace = ReturnType<typeof useDocumentScope>
