<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api'
import type { Job } from '../types'
import AppIcon from './AppIcon.vue'
const props = defineProps<{ job: Job }>()
const emit = defineEmits<{ updated: [Job] }>()
const submitting = ref(false), requested = ref(false), error = ref('')
const stages = [['queued', '等待执行'], ['reading', '读取原稿'], ['checking', '检查格式'], ['verifying', '核对完整性'], ['reporting', '生成报告']]
const stage = computed(() => stages.findIndex(([id]) => id === (props.job.stage || (props.job.status === 'queued' ? 'queued' : 'reading'))))
const cancellation = computed(() => Boolean(props.job.cancel_requested || requested.value))
watch(() => props.job.id, () => { requested.value = false; submitting.value = false; error.value = '' })
async function cancel() {
  if (submitting.value || cancellation.value) return
  const id = props.job.id
  submitting.value = true; error.value = ''
  try {
    const updated = await api.cancelJob(id)
    if (props.job.id !== id) return
    requested.value = true; emit('updated', updated)
  } catch (value) { if (props.job.id === id) error.value = value instanceof Error ? value.message : String(value) }
  finally { if (props.job.id === id) submitting.value = false }
}
</script>

<template>
  <section class="panel job-progress" aria-label="检测进度">
    <div class="progress-heading" role="status" aria-live="polite"><span class="spinner" aria-hidden="true" /><strong>{{ cancellation ? '正在等待安全停止' : stages[stage]?.[1] || '正在检测' }}</strong></div>
    <ol class="progress-stages"><li v-for="([id, label], index) in stages" :key="id" :class="{ current: stage === index, done: stage > index }" :aria-current="stage === index ? 'step' : undefined"><span aria-hidden="true"><AppIcon v-if="stage > index" name="check" :size="14" /><template v-else>{{ index + 1 }}</template></span>{{ label }}</li></ol>
    <div class="progress-footer"><p class="field-help">{{ cancellation ? '当前读取或检查完成后停止，不会生成完整检测结论。' : '结果会自动更新。' }}</p><button class="button secondary" type="button" :disabled="submitting || cancellation" @click="cancel">{{ cancellation ? '已请求取消' : submitting ? '正在请求…' : '取消检测' }}</button></div>
    <p v-if="error" class="notice error-notice" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.job-progress { padding: var(--panel-padding, 22px); margin-block: 20px; }
.progress-heading, .progress-footer { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
.progress-footer { justify-content: space-between; }
.progress-footer p { margin: 0; }
.progress-stages { display: flex; flex-wrap: wrap; padding: 0; gap: 12px 20px; margin-block: 20px; list-style: none; }
.progress-stages li { display: flex; gap: 8px; align-items: center; color: var(--muted); font-size: 15px; }
.progress-stages span { display: grid; place-items: center; width: 26px; height: 26px; border: 1px solid var(--line); border-radius: 50%; }
.progress-stages .current { color: var(--brand); font-weight: 600; }
.progress-stages .current span { background: var(--action-bg); color: var(--brand-on); }
.progress-stages .done { color: var(--success); }
@media (max-width: 600px) { .progress-stages { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); } .progress-footer { align-items: stretch; flex-direction: column; } }
</style>
