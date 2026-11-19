import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useAuditFiles } from './useAuditFiles'
import type { AuditDefaults } from '../utils/auditRoute'

export function useAuditDraft() {
  const files = useAuditFiles()
  const profileId = ref(''), kind = ref('thesis'), collectionId = ref(''), renderWord = ref(false)
  const revisionOf = ref('')
  const version = ref(0)
  watch([files.documentFile, files.pdfFile, profileId, kind, collectionId, renderWord, revisionOf], () => { version.value += 1 }, { flush: 'sync' })
  function applyDefaults(defaults: AuditDefaults) {
    profileId.value = defaults.profile; kind.value = defaults.kind; collectionId.value = defaults.collection
  }
  function clearFiles() { files.documentFile.value = null; renderWord.value = false; revisionOf.value = '' }
  function beforeUnload(event: BeforeUnloadEvent) {
    if (!files.documentFile.value) return
    event.preventDefault(); event.returnValue = ''
  }
  onMounted(() => window.addEventListener('beforeunload', beforeUnload))
  onUnmounted(() => window.removeEventListener('beforeunload', beforeUnload))
  return { files, profileId, kind, collectionId, renderWord, revisionOf, version, applyDefaults, clearFiles }
}

export type AuditDraft = ReturnType<typeof useAuditDraft>
