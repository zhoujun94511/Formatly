<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { Job } from '../types'
import { useOcrEvidence } from '../composables/useOcrEvidence'
import PageEvidence from './PageEvidence.vue'
import AppIcon from './AppIcon.vue'
const props = defineProps<{ job: Job }>()
const state = useOcrEvidence(() => props.job)
const { location, evidence, loading, error } = state
const dialog = ref<HTMLDialogElement>(), title = ref<HTMLElement>()
let opener: HTMLElement | null = null
watch(location, async value => {
  if (value === null) { dialog.value?.close(); if (opener?.isConnected) opener.focus(); return }
  await nextTick()
  if (location.value !== value) return
  if (!dialog.value?.open) dialog.value?.showModal()
  title.value?.focus()
})
function open(value: string) { opener = document.activeElement as HTMLElement; void state.open(value) }
onBeforeUnmount(() => dialog.value?.close())
defineExpose({ open })
</script>
<template>
  <dialog ref="dialog" class="dialog ocr-evidence-dialog" aria-labelledby="ocr-evidence-title" @cancel.prevent="state.close" @click="($event.target === dialog) && state.close()">
    <div class="dialog-heading"><h2 id="ocr-evidence-title" ref="title" tabindex="-1">识别文字与原页</h2><button type="button" class="icon-button" aria-label="关闭原页核对" @click="state.close"><AppIcon name="close" :size="18" /></button></div>
    <p v-if="loading" role="status">正在读取原页…</p>
    <p v-if="error" class="notice error-notice" role="alert">{{ error }} <button v-if="location" type="button" class="text-button" :disabled="loading" @click="state.open(location)">重新读取</button></p>
    <template v-if="evidence">
      <p>{{ evidence.location }}</p>
      <dl><div><dt>首次识别</dt><dd>{{ evidence.observation.primary_text }}</dd></div><div v-if="evidence.observation.alternative"><dt>补充识别</dt><dd>{{ evidence.observation.alternative.text }}</dd></div></dl>
      <p class="field-help">请以原页为准核对；补充识别不会替换原稿或检测文本。</p>
      <PageEvidence v-if="evidence.preview" :preview="evidence.preview" />
      <p v-for="item in evidence.limitations" :key="item" class="notice warm-notice">{{ item }}</p>
    </template>
  </dialog>
</template>
<style scoped>
.ocr-evidence-dialog { width: min(900px, calc(100vw - 32px)); }
p, dd { overflow-wrap: anywhere; white-space: pre-wrap; }
dl > div { display: grid; grid-template-columns: 5rem minmax(0, 1fr); gap: 8px; margin-block: 10px; }
dt { color: var(--muted); } dd { margin: 0; min-width: 0; }
@media (max-width: 480px) { dl > div { grid-template-columns: minmax(0, 1fr); gap: 4px; } }
</style>
