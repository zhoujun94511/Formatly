import { computed, onBeforeUnmount, onUnmounted, ref, watch, type Ref } from 'vue'
import { api, ApiError } from '../api'
import type { School } from '../types'
import type { SavedRequirementDraft, useRequirementEditor } from './useRequirementEditor'

export interface SchoolDraftRecord { school_id: string; draft_version: number; draft: SavedRequirementDraft | null }
type Editor = ReturnType<typeof useRequirementEditor>
const fingerprint = (draft: SavedRequirementDraft) => JSON.stringify({ base_school_version: draft.base_school_version,
  baseline: draft.baseline, requirements: draft.requirements, refresh_conflicts: draft.refresh_conflicts })

export function useSchoolDraftPersistence(selected: Ref<School | null>, editor: Editor) {
  const loading = ref(false), saving = ref(false), error = ref(''), notice = ref('')
  const pendingDraft = ref<SavedRequirementDraft | null>(null)
  const draftVersion = ref(0), conflict = ref(false), ready = ref(false)
  const savedFingerprint = ref('')
  const hasSavedDraft = ref(false)
  const unsaved = computed(() => editor.dirty.value && (!ready.value || fingerprint(editor.exportDraft()) !== savedFingerprint.value))
  let activeId = '', generation = 0, disposed = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let activeSave: Promise<boolean> | null = null
  function cancelTimer() { if (timer !== undefined) clearTimeout(timer); timer = undefined }
  const valid = (id: string, request: number) => !disposed && id === activeId && request === generation
  const message = (value: unknown) => value instanceof Error ? value.message : String(value)

  async function read() {
    const school = selected.value
    if (!school) return
    const id = school.id, request = ++generation
    cancelTimer(); loading.value = true; ready.value = false; error.value = ''; notice.value = ''; conflict.value = false
    try {
      const result = await api.schoolDraft(id)
      if (!valid(id, request)) return
      draftVersion.value = result.draft_version; pendingDraft.value = result.draft
      hasSavedDraft.value = !!result.draft; ready.value = true
      savedFingerprint.value = result.draft ? fingerprint(result.draft) : ''
      if (!result.draft && editor.dirty.value) schedule()
    } catch (value) { if (valid(id, request)) error.value = message(value) }
    finally { if (valid(id, request)) loading.value = false }
  }
  watch(() => selected.value?.id || '', id => {
    if (id === activeId) return
    activeId = id; generation += 1; cancelTimer(); pendingDraft.value = null; savedFingerprint.value = ''
    ready.value = false; conflict.value = false; error.value = ''; notice.value = ''; hasSavedDraft.value = false
    activeSave = null; saving.value = false
    if (id) void read()
  }, { immediate: true })

  function schedule() {
    cancelTimer()
    if (!ready.value || pendingDraft.value || conflict.value || !editor.dirty.value || disposed) return
    timer = setTimeout(() => { timer = undefined; void save() }, 700)
  }
  async function save(): Promise<boolean> {
    cancelTimer()
    if (activeSave) { await activeSave; if (unsaved.value && !conflict.value) return save(); return !unsaved.value }
    const school = selected.value
    if (!school || !ready.value || pendingDraft.value || conflict.value || disposed) return false
    const draft = editor.exportDraft(), hash = fingerprint(draft)
    if (hash === savedFingerprint.value) return true
    const id = school.id, request = generation
    saving.value = true; error.value = ''; notice.value = ''
    const task = (async () => {
      try {
        const result = await api.saveSchoolDraft(id, { ...draft, expected_draft_version: draftVersion.value })
        if (!valid(id, request)) return false
        draftVersion.value = result.draft_version; hasSavedDraft.value = true
        savedFingerprint.value = hash; editor.markDraftSaved(draft); notice.value = '草稿已保存，尚未生成检测方案。'
        return true
      } catch (value) {
        if (valid(id, request)) { error.value = message(value); conflict.value = value instanceof ApiError && value.status === 409 }
        return false
      } finally { if (valid(id, request)) saving.value = false }
    })()
    activeSave = task
    const success = await task
    if (activeSave === task) activeSave = null
    if (success && unsaved.value) schedule()
    return success
  }
  async function restore() {
    const school = selected.value, saved = pendingDraft.value
    if (!school || !saved) return
    editor.restoreDraft(school, saved); pendingDraft.value = null; notice.value = '已恢复草稿，请继续核对后生成方案。'
    // The editor merged a newer school revision with the saved baseline.
    if (unsaved.value) schedule()
  }
  function keepLocal() {
    if (!pendingDraft.value) return
    pendingDraft.value = null; savedFingerprint.value = ''; notice.value = '已保留当前编辑，将另存为最新草稿。'; schedule()
  }
  async function discard(resetEditor = true) {
    cancelTimer()
    const school = selected.value
    if (!school || !ready.value || loading.value || disposed) return false
    const id = school.id, request = generation
    if (activeSave) await activeSave
    if (!valid(id, request)) return false
    saving.value = true; error.value = ''; conflict.value = false
    try {
      const result = await api.discardSchoolDraft(id, draftVersion.value)
      if (!valid(id, request)) return false
      draftVersion.value = result.draft_version; pendingDraft.value = null; hasSavedDraft.value = false; savedFingerprint.value = ''
      if (resetEditor) editor.acceptLatest()
      notice.value = resetEditor ? '草稿已丢弃，已读取已保存要求。' : ''
      return true
    } catch (value) { if (valid(id, request)) { error.value = message(value); conflict.value = value instanceof ApiError && value.status === 409 }; return false }
    finally { if (valid(id, request)) saving.value = false }
  }
  watch([editor.drafts, editor.refreshConflicts, editor.schoolVersion], () => {
    notice.value = ''; schedule()
  }, { deep: true })
  async function flush() { cancelTimer(); if (activeSave) await activeSave; return editor.dirty.value ? save() : true }
  onBeforeUnmount(() => { cancelTimer(); if (editor.dirty.value && ready.value && !pendingDraft.value && !conflict.value) void save() })
  onUnmounted(() => { disposed = true; generation += 1; cancelTimer() })
  return { loading, saving, error, notice, pendingDraft, draftVersion, conflict, ready, unsaved, hasSavedDraft,
    read, save, restore, keepLocal, discard, flush }
}
