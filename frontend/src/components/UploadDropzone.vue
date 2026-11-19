<script setup lang="ts">
import { nextTick, ref, useId, watch } from 'vue'
import { documentAccept, documentFileError } from '../utils/documents'
import AppIcon from './AppIcon.vue'

const props = withDefaults(defineProps<{ modelValue: File | null; disabled?: boolean; label?: string }>(), { label: '检测文档' })
const emit = defineEmits<{ 'update:modelValue': [File | null] }>()
const dragging = ref(false)
const dragDepth = ref(0)
const input = ref<HTMLInputElement>()
const dropzone = ref<HTMLDivElement>()
const error = ref('')
const errorId = useId()
const formatsId = useId()

watch(() => props.disabled, disabled => {
  if (disabled) { dragging.value = false; dragDepth.value = 0 }
})

function openPicker() {
  if (!props.disabled) input.value?.click()
}

function clearInput() {
  if (input.value) input.value.value = ''
}

function rejectFile(message: string) {
  clearInput()
  emit('update:modelValue', null)
  error.value = message
}

function choose(file?: File) {
  clearInput()
  if (props.disabled || !file) return
  error.value = ''
  const validation = documentFileError(file)
  if (validation) { rejectFile(validation); return }
  emit('update:modelValue', file)
}

function remove() {
  if (props.disabled) return
  clearInput()
  error.value = ''
  emit('update:modelValue', null)
  void nextTick(() => {
    if (!props.disabled && dropzone.value?.isConnected) dropzone.value.focus({ preventScroll: true })
  })
}

function drop(event: DragEvent) {
  event.preventDefault()
  dragging.value = false
  dragDepth.value = 0
  if (props.disabled) return
  const files = event.dataTransfer?.files
  if (files?.length !== 1) {
    rejectFile('请每次选择一个文档。')
    return
  }
  choose(files[0])
}

function enterDrag() {
  if (props.disabled) return
  dragDepth.value += 1
  dragging.value = true
}

function leaveDrag() {
  dragDepth.value = Math.max(0, dragDepth.value - 1)
  if (!dragDepth.value) dragging.value = false
}

function format(bytes = 0) {
  return bytes < 1024 ? `${bytes} B`
    : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB`
      : `${(bytes / 1048576).toFixed(1)} MB`
}
</script>

<template>
  <div>
    <div
      ref="dropzone"
      class="dropzone"
      :class="{ dragging, 'has-file': modelValue }"
      role="button"
      :tabindex="disabled ? -1 : 0"
      :aria-disabled="!!disabled"
      :aria-describedby="error ? `${formatsId} ${errorId}` : formatsId"
      @click="openPicker"
      @keydown.enter.prevent="openPicker"
      @keydown.space.prevent="openPicker"
      @dragenter.prevent="enterDrag"
      @dragover.prevent="dragging = !disabled"
      @dragleave.prevent="leaveDrag"
      @drop="drop"
    >
      <span class="upload-illustration"><AppIcon :name="modelValue ? 'check' : 'upload'" :size="27" /></span>
      <strong>{{ modelValue ? '文档已添加' : '拖拽文件至此，或点击上传' }}<span class="visually-hidden">，选择{{ label }}</span></strong>
      <span>{{ modelValue ? '点击更换文档' : '支持以下文档格式' }}</span>
      <span :id="formatsId" class="file-type-badge">DOCX / PDF / TXT / MD / JSON</span>
    </div>
    <input
        ref="input"
        hidden
        tabindex="-1"
        type="file"
        :accept="documentAccept"
        :disabled="disabled"
        aria-hidden="true"
        @click.stop
        @change="choose(($event.target as HTMLInputElement).files?.[0])"
      />
    <div v-if="modelValue" class="selected-file">
      <span class="file-icon"><AppIcon name="file" :size="20" /></span>
      <div>
        <strong>{{ modelValue.name }}</strong>
        <small>{{ format(modelValue.size) }} · 已就绪</small>
      </div>
      <button type="button" class="icon-button" :aria-label="`移除${label}`" :disabled="disabled" @click="remove"><AppIcon name="close" :size="18" /></button>
    </div>
    <p v-if="error" :id="errorId" class="notice error-notice" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.dropzone[aria-disabled="true"] { cursor: not-allowed; opacity: .65; }
.file-type-badge { max-width: 100%; flex-wrap: wrap; white-space: normal; text-align: center; }
</style>

