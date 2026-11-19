<script setup lang="ts">
import { computed, ref, toRef, watch } from 'vue'
import StatusBadge from '../components/StatusBadge.vue'
import AppIcon from '../components/AppIcon.vue'
import DocumentScopePicker from '../components/DocumentScopePicker.vue'
import { useBatchAudit } from '../composables/useBatchAudit'
import { isHiddenPreset, profileLabel, profileMatchesKind } from '../utils/materials'
import type { Profile } from '../types'
const props = defineProps<{ profiles: Profile[]; selectedId?: string }>()
const emit = defineEmits<{ navigate: [string] }>()
const state = useBatchAudit(toRef(props, 'profiles'), toRef(props, 'selectedId'))
const matchingProfiles = computed(() => props.profiles.filter(profile => !isHiddenPreset(profile) && profileMatchesKind(profile, state.kind.value)))
watch(state.kind, () => {
  const selected = props.profiles.find(profile => profile.id === state.profileId.value)
  if (selected && (isHiddenPreset(selected) || !profileMatchesKind(selected, state.kind.value))) state.profileId.value = ''
})
const fileInput = ref<HTMLInputElement>()
function choose(event: Event) { const input = event.target as HTMLInputElement; state.choose(Array.from(input.files || [])); input.value = '' }
async function submit() { const id = await state.submit(); if (id) emit('navigate', `batch/${id}`) }
async function recoverSubmission() { const id = await state.recoverSubmission(); if (id) emit('navigate', `batch/${id}`) }
async function retry(id: string) { const next = await state.retry(id); if (next) emit('navigate', `job/${next}`) }
</script>
<template>
  <div class="page">
    <div class="page-heading"><div><h1>批量检测</h1><p>为多份文档使用同一方案，分别生成检测报告。</p></div><button class="button secondary" type="button" @click="emit('navigate', 'new')">单份检测</button></div>
    <p v-if="state.error.value" class="notice error-notice" role="alert">{{ state.error.value }}
      <button v-if="selectedId" class="text-button" type="button" :disabled="state.loading.value" @click="state.load">重新读取</button>
      <button v-else-if="state.preflightFailed.value" class="text-button" type="button" :disabled="state.checking.value || state.busy.value" @click="state.check">重新核对方案</button>
      <button v-else-if="state.canRecoverSubmission.value" class="text-button" type="button" @click="recoverSubmission">重试原批次</button>
    </p>
    <form v-if="!selectedId" class="panel batch-form" :aria-busy="state.busy.value" @submit.prevent="submit">
      <fieldset :disabled="state.busy.value" class="batch-fields">
        <legend class="visually-hidden">批量检测设置</legend>
        <div class="batch-settings"><h2>检测设置</h2><label class="field">规则方案<select v-model="state.profileId.value" required><option value="" disabled>请选择方案</option><option v-for="profile in matchingProfiles" :key="profile.id" :value="profile.id">{{ profileLabel(profile) }}</option></select></label><label class="field">材料类型<select v-model="state.kind.value"><option value="thesis">毕业论文</option><option value="intern">实习报告</option><option value="certificate">实习证明</option></select></label></div>
        <section class="batch-upload" aria-labelledby="batch-upload-title"><div class="batch-upload-heading"><h2 id="batch-upload-title">待检测原稿</h2><span v-if="state.files.value.length" class="muted">已选 {{ state.files.value.length }} 份</span></div>
        <button class="batch-picker" type="button" aria-describedby="batch-file-help" @click="fileInput?.click()"><span class="batch-upload-icon"><AppIcon name="upload" /></span><strong>{{ state.files.value.length ? '重新选择原稿' : '点击选择多份原稿' }}</strong><span>DOCX、PDF、TXT、MD、JSON</span></button>
        <input ref="fileInput" class="visually-hidden" tabindex="-1" aria-hidden="true" type="file" multiple accept=".docx,.pdf,.txt,.md,.json" @change="choose" />
        <p id="batch-file-help" class="field-help">每批最多 20 份，单份 ≤ 40 MB，合计 ≤ 80 MB。</p>
        <p v-if="state.fileError.value" class="notice error-notice" role="alert">{{ state.fileError.value }}</p>
        <ul v-if="state.files.value.length" class="batch-files" tabindex="0" aria-label="已选原稿"><li v-for="(file, index) in state.files.value" :key="index"><AppIcon name="file" /><span>{{ file.name }}</span><button type="button" class="text-button" :aria-label="`移除${file.name}`" @click="state.choose(state.files.value.filter((_, i) => i !== index))">移除</button></li></ul>
        </section>
        <section v-if="state.scopeReviews.value.length" class="batch-scope" aria-labelledby="batch-scope-title">
          <div class="batch-upload-heading"><h2 id="batch-scope-title">逐份确认原稿范围</h2><span class="muted">已就绪 {{ state.scopeReviews.value.filter(item => item.ready).length }} / {{ state.scopeReviews.value.length }} 份</span></div>
          <label class="field" for="batch-scope-file">当前原稿<select id="batch-scope-file" v-model.number="state.scopeIndex.value"><option v-for="item in state.scopeReviews.value" :key="item.index" :value="item.index">{{ item.index + 1 }}. {{ item.name }} · {{ item.complete ? '已确认' : item.ready ? '使用原方案' : '待确认' }}</option></select></label>
          <p class="field-help">每份原稿单独选择适用范围，切换原稿会保留已确认的选择。</p>
          <DocumentScopePicker v-if="state.documentScope.value" :key="state.scopeSlot.value" :workspace="state.documentScope.value" :disabled="state.busy.value" has-file />
        </section>
        <div class="batch-submit"><div class="batch-readiness"><p v-if="state.checking.value" role="status" class="field-help">正在核对方案能力…</p>
        <div v-for="(preflight, format) in state.preflights.value" :key="format" class="notice" :class="preflight?.available ? 'neutral-notice' : 'error-notice'">{{ format.toUpperCase() }}：{{ preflight?.available ? '方案可用' : '当前方案不可用' }}<p v-for="warning in preflight?.warnings" :key="warning">{{ warning }}</p></div></div>
        <p v-if="!state.checking.value && !state.files.value.length" class="field-help" role="status">请选择多份原稿。<button class="text-button" type="button" @click="emit('navigate', 'new?source=school')">还没有学校方案？上传学校模板</button></p>
        <p v-if="!state.checking.value && !state.scopesReady.value" class="field-help" role="status">请逐份完成原稿范围确认，无法匹配的要求可选择暂不匹配。</p>
        <button class="button primary" type="submit" :disabled="!state.canSubmit.value">{{ state.busy.value ? '正在提交…' : `开始检测${state.files.value.length ? `（${state.files.value.length} 份）` : ''}` }}<AppIcon name="arrow-right" /></button></div>
      </fieldset>
    </form>
    <section v-if="state.batch.value" class="panel batch-results-panel" aria-labelledby="batch-results-title">
      <div class="section-heading"><h2 id="batch-results-title">本批结果</h2><button class="button secondary" type="button" :disabled="state.loading.value" @click="state.load">刷新</button></div>
      <ul class="batch-results"><li v-for="item in state.batch.value.items" :key="item.index"><div class="batch-item-name"><strong>{{ item.filename }}</strong><p v-if="item.error" class="error-text">{{ item.error }}。请修正该文件后单独提交，其他结果已保留。</p><StatusBadge v-if="item.job" :status="item.job.status" /></div><div class="batch-actions"><button v-if="item.job_id" class="button secondary" type="button" @click="emit('navigate', `job/${item.job_id}`)">查看结果</button><button v-if="item.job && ['queued', 'running'].includes(item.job.status)" class="button secondary" type="button" :disabled="!!state.actionId.value || !!item.job.cancel_requested" @click="state.cancel(item.job.id)">{{ item.job.cancel_requested ? '等待取消' : '取消' }}</button><button v-if="item.job && ['failed', 'interrupted', 'cancelled'].includes(item.job.status)" class="button secondary" type="button" :disabled="!!state.actionId.value" @click="retry(item.job.id)">单独重试</button><button v-if="item.error && !item.job_id" class="button secondary" type="button" @click="emit('navigate', 'new')">去单份检测</button></div></li></ul>
    </section>
    <p v-else-if="state.loading.value" class="empty-state" role="status">正在读取批次…</p>
  </div>
</template>
<style scoped>
.batch-form { padding: 0; }
.batch-fields { display: grid; grid-template-columns: minmax(0, .8fr) minmax(0, 1.2fr); min-width: 0; border: 0; padding: 0; margin: 0; }
.batch-settings { display: flex; flex-direction: column; gap: 22px; padding: 28px; border-right: 1px solid var(--line); }
.batch-settings h2, .batch-upload-heading h2 { font-size: 19px; }
.batch-settings .field, .batch-scope > .field { display: grid; gap: 8px; font-size: 15px; font-weight: 600; }
.batch-settings select, .batch-scope > .field > select { width: 100%; min-width: 0; min-height: 44px; padding: 9px 12px; border: 1px solid var(--line-strong); border-radius: 8px; background: var(--surface); color: var(--ink); font-size: 15px; font-weight: 400; }
.batch-scope { grid-column: 1 / -1; min-width: 0; padding: 24px 28px; border-top: 1px solid var(--line); }
.batch-scope h2 { font-size: 19px; }
.batch-upload { min-width: 0; padding: 28px; }
.batch-upload-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
.batch-upload-heading > span { font-size: 14px; }
.batch-picker { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; width: 100%; min-height: 190px; padding: 24px 16px; border: 1px dashed var(--line-strong); border-radius: 10px; background: var(--canvas); color: var(--ink); text-align: center; }
.batch-picker:hover { border-color: var(--brand); background: var(--brand-soft); }
.batch-picker:disabled { cursor: not-allowed; }
.batch-picker > strong { font-size: 16px; font-weight: 600; }
.batch-picker > span:last-child { font-size: 13px; color: var(--muted); }
.batch-upload-icon { display: grid; place-items: center; width: 44px; height: 44px; margin-bottom: 2px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); color: var(--brand); }
.batch-upload-icon svg { width: 22px; height: 22px; }
.batch-upload > .field-help { font-size: 13px; margin-bottom: 0; }
.batch-files, .batch-results { list-style: none; padding: 0; margin: 0; }
.batch-files { max-height: 300px; overflow-y: auto; overscroll-behavior: contain; margin-top: 16px; border-top: 1px solid var(--line); }
.batch-files li, .batch-results li { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 0; border-bottom: 1px solid var(--line); }
.batch-files li:last-child, .batch-results li:last-child { border-bottom: 0; }
.batch-files li > svg { flex-shrink: 0; color: var(--muted); }
.batch-files span, .batch-item-name { min-width: 0; overflow-wrap: anywhere; }
.batch-files span { flex: 1; font-size: 15px; }
.batch-files .text-button { flex-shrink: 0; font-size: 14px; }
.batch-submit { grid-column: 1 / -1; display: flex; align-items: center; justify-content: space-between; gap: 20px; flex-wrap: wrap; padding: 20px 28px; border-top: 1px solid var(--line); }
.batch-readiness { flex: 1; min-width: 0; }
.batch-readiness .notice { margin-block: 0 8px; font-size: 14px; }
.batch-readiness .notice:last-child { margin-bottom: 0; }
.batch-readiness p { margin-block: 0; }
.batch-submit > .button { margin-left: auto; }
.batch-results-panel { padding: 24px; }
.batch-actions { display: flex; gap: 8px; flex-wrap: wrap; flex-shrink: 0; }
.batch-item-name { flex: 1; }
.batch-item-name strong { font-size: 16px; font-weight: 600; }
.batch-item-name .status-badge { margin-top: 8px; }
.batch-item-name p { margin-block: 8px; font-size: 14px; }
.batch-results .error-text { color: var(--danger); }
.section-heading { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; padding-bottom: 20px; margin: 0; border-bottom: 1px solid var(--line); }
@container workspace (max-width: 800px) { .batch-fields { grid-template-columns: 1fr; } .batch-settings { border-right: 0; border-bottom: 1px solid var(--line); } }
@media(max-width: 640px) { .batch-fields { grid-template-columns: 1fr; } .batch-settings { border-right: 0; border-bottom: 1px solid var(--line); } .batch-settings, .batch-upload, .batch-scope, .batch-results-panel { padding: 20px; } .batch-submit { padding: 20px; align-items: stretch; flex-direction: column; gap: 12px; } .batch-submit > .button { width: 100%; } .batch-results li { align-items: stretch; flex-direction: column; gap: 12px; } .batch-actions > .button { flex: 1 1 auto; } }
</style>
