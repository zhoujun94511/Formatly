import { computed, ref, watch } from 'vue'
import { documentFormat, maxDocumentBytes } from '../utils/documents'

export function useAuditFiles() {
  const documentFile = ref<File | null>(null), pdfFile = ref<File | null>(null), pdfError = ref('')
  const inputFormat = computed(() => documentFormat(documentFile.value?.name || '') || 'docx')
  const canPairPdf = computed(() => inputFormat.value === 'docx')
  function removePdf() { pdfFile.value = null; pdfError.value = '' }
  function choosePdf(file?: File) {
    if (!file || !canPairPdf.value) return
    removePdf()
    if (!file.name.toLowerCase().endsWith('.pdf')) { pdfError.value = '配对文件需要使用 .pdf 格式。'; return }
    if (file.size === 0 || file.size > maxDocumentBytes) { pdfError.value = 'PDF 必须非空且不超过 40 MB。'; return }
    pdfFile.value = file
  }
  watch(documentFile, removePdf, { flush: 'sync' })
  return { documentFile, pdfFile, pdfError, inputFormat, canPairPdf, removePdf, choosePdf }
}
