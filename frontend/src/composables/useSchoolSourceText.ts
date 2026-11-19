import { computed, ref, watch, type Ref } from 'vue'
import { documentFormat } from '../utils/documents'

export const maxSchoolTextBytes = 1024 * 1024

export function useSchoolSourceText(file: Ref<File | null>) {
  const transcription = ref('')
  const sourceIsPdf = computed(() => documentFormat(file.value?.name || '') === 'pdf')
  const transcriptionBytes = computed(() => new TextEncoder().encode(transcription.value).byteLength)
  const transcriptionError = computed(() => sourceIsPdf.value && transcription.value.trim()
    && transcriptionBytes.value > maxSchoolTextBytes ? '校正文本超过 1 MB（UTF-8），请缩短后上传。' : '')
  watch(file, () => { transcription.value = '' }, { flush: 'sync' })
  return { transcription, sourceIsPdf, transcriptionBytes, transcriptionError }
}
