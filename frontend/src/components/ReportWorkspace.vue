<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { Job } from '../types'
import { useReportWorkspace } from '../composables/useReportWorkspace'
import { displayEvidence, displayRuleEvidence, displayLocation, displaySource } from '../utils/report'
import { automaticTargets } from '../utils/materials'
import type { ComparisonGroup, ReviewDraftCache } from '../utils/reportWorkspace'
import PageEvidence from './PageEvidence.vue'
import AppIcon from './AppIcon.vue'
import ListPagination from './ListPagination.vue'
import { usePagedItems } from '../composables/usePagedItems'

const props = defineProps<{ job: Job; draftCache?: ReviewDraftCache }>()
const workspace = useReportWorkspace(() => props.job, undefined, props.draftCache)
const { index, evidence, reviews, comparison, eligible, canSaveReview, loading, saving, comparing, refreshingReviews, error, reviewError, compareError, draft, saved, unsaved, restoredDraft } = workspace
const dialog = ref<HTMLDialogElement>(), title = ref<HTMLElement>()
const opener = ref<HTMLElement | null>(null)
const groups: [ComparisonGroup, string][] = [['resolved', '已解决'], ['remaining', '仍存在'], ['new', '新增'], ['incomparable', '无法比较']]
const selectedGroup = ref<ComparisonGroup>('resolved')
const entries = computed(() => comparison.value?.groups[selectedGroup.value] || [])
const { page, displayed, setPage } = usePagedItems(entries)
const selectedIssue = computed(() => index.value === null ? undefined : props.job.result?.issues?.[index.value])
const parentId = computed(() => props.job.repair?.source_job_id || (props.job as Job & { revision_of_job_id?: string }).revision_of_job_id)
watch(index, async value => {
  if (value === null) { dialog.value?.close(); opener.value?.focus(); return }
  await nextTick(); if (!dialog.value?.open) dialog.value?.showModal(); title.value?.focus()
})
function open(selected: number) { opener.value = document.activeElement as HTMLElement; void workspace.openIssue(selected) }
function close() { workspace.closeIssue() }
onBeforeUnmount(() => dialog.value?.close())
defineExpose({ open })
</script>

<template>
  <section v-if="parentId" class="panel comparison-panel" aria-labelledby="comparison-title">
    <div class="panel-heading"><h2 id="comparison-title">复检对照</h2><button type="button" class="button secondary" :disabled="!eligible || comparing" @click="workspace.loadComparison">{{ comparing ? '正在比较…' : comparison ? '重新比较' : '比较原检测' }}</button></div>
    <p class="field-help"><a :href="`#job/${parentId}`">查看原检测</a> · 按同一规则和可核对的位置比较自动检查。</p>
    <p v-if="compareError" class="notice error-notice" role="alert">{{ compareError }}</p>
    <template v-if="comparison">
      <p :class="comparison.available ? 'field-help' : 'notice warm-notice'">{{ comparison.reason }}</p>
      <template v-if="comparison.available">
        <div class="filter-chips"><button v-for="[id, label] in groups" :key="id" class="filter-chip" :class="{ active: selectedGroup === id }" :aria-pressed="selectedGroup === id" type="button" @click="selectedGroup = id">{{ label }} {{ comparison.summary[id] || 0 }}</button></div>
        <ListPagination :page="page" :total="entries.length" label="复检对照分页" @change="setPage" />
        <div v-for="(entry, entryIndex) in displayed" :key="`${page}-${entryIndex}`" class="compared-check"><strong>{{ automaticTargets.find(([target]) => target === entry.target)?.[1] || '格式检查项' }}</strong><p>{{ displayEvidence(entry.location) }}</p><dl><div><dt>格式要求</dt><dd>{{ displayRuleEvidence(entry.expected, entry.target) }}</dd></div><div><dt>原检测</dt><dd>{{ displayRuleEvidence(entry.before, entry.target) }}</dd></div><div><dt>本次检测</dt><dd>{{ displayRuleEvidence(entry.after, entry.target) }}</dd></div></dl><p v-if="entry.reason" class="field-help">{{ entry.reason }}</p></div>
        <p v-if="!entries.length" class="empty-state">此类暂无检查项</p>
      </template>
    </template>
  </section>

  <Teleport to="body"><dialog ref="dialog" class="dialog issue-evidence-dialog" aria-labelledby="issue-evidence-title" @cancel.prevent="close" @click="($event.target === dialog) && close()">
    <div class="dialog-heading"><h2 id="issue-evidence-title" ref="title" tabindex="-1">问题位置与依据</h2><button class="icon-button" type="button" aria-label="关闭问题证据" @click="close"><AppIcon name="close" :size="18" /></button></div>
    <p v-if="loading" role="status">正在读取原稿证据…</p>
    <p v-if="error" class="notice error-notice" role="alert">{{ error }} <button v-if="index !== null" type="button" class="text-button" @click="workspace.openIssue(index)">重新读取</button></p>
    <template v-if="evidence">
      <div v-if="selectedIssue" class="issue-detail"><div><span class="issue-detail-label">要求格式</span><div class="issue-detail-value">{{ displayRuleEvidence(selectedIssue.expected, selectedIssue.rule_id) }}</div></div><div><span class="issue-detail-label">实际格式</span><div class="issue-detail-value">{{ displayRuleEvidence(selectedIssue.actual, selectedIssue.rule_id) }}</div></div></div>
      <h3>原稿位置</h3><p>{{ displayLocation(evidence.location) }}</p>
      <PageEvidence v-if="evidence.preview" :preview="evidence.preview" />
      <blockquote v-for="(snippet, snippetIndex) in evidence.snippets" :key="snippetIndex"><p>{{ snippet.text }}</p><small>{{ displayLocation(snippet.location) }}<span v-if="snippet.method === 'ocr'"> · 图像识别，需核对</span></small></blockquote>
      <p v-for="limitation in evidence.limitations" :key="limitation" class="field-help">{{ limitation }}</p>
      <h3>要求依据</h3><p v-for="(source, sourceIndex) in evidence.sources" :key="sourceIndex" class="source-evidence">{{ displaySource(source) }}</p><p v-if="!evidence.sources.length" class="field-help">此项未记录要求来源。</p>
      <form class="review-form" @submit.prevent="workspace.saveReview">
        <h3>人工复核记录</h3><p class="field-help">单独保存复核意见，自动检测结论保持原样。</p>
        <fieldset :disabled="saving || refreshingReviews || !reviews"><div class="form-group"><label for="issue-review-status">处理状态</label><select id="issue-review-status" v-model="draft.status"><option value="pending">待处理</option><option value="checked">人工已核对</option><option value="suspected_false_positive">疑似误报</option></select></div><div class="form-group"><label for="issue-review-note">备注 <span class="optional-label">可选</span></label><textarea id="issue-review-note" v-model="draft.note" rows="3" maxlength="2000" /></div></fieldset>
        <p v-if="reviewError" class="notice error-notice" role="alert">{{ reviewError }}</p>
        <p v-if="saved" class="field-help" role="status">复核意见已保存。</p>
        <p v-else-if="unsaved" class="field-help" role="status">{{ restoredDraft ? '已恢复未保存的复核草稿。' : '复核意见尚未保存。' }}关闭后可在本次会话继续编辑。</p>
        <button v-if="unsaved" class="text-button" type="button" :disabled="saving || !reviews" @click="workspace.discardDraft">放弃未保存修改</button>
        <div class="review-actions"><button class="text-button" type="button" :disabled="saving || refreshingReviews" @click="workspace.refreshReviews">{{ refreshingReviews ? '正在读取…' : '读取最新复核记录' }}</button><button class="button primary" type="submit" :disabled="!canSaveReview">{{ saving ? '正在保存…' : '保存复核意见' }}</button></div>
      </form>
    </template>
  </dialog></Teleport>
</template>

<style scoped>
.comparison-panel { padding: var(--panel-padding, 22px); margin-block: 20px; min-width: 0; }
.compared-check { padding-block: 14px; border-top: 1px solid var(--line); overflow-wrap: anywhere; }
.compared-check dl { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.compared-check dt, figcaption { color: var(--muted); font-size: 14px; }
.compared-check dd { margin: 0; white-space: pre-wrap; }
.issue-evidence-dialog { width: min(900px, calc(100vw - 32px)); }
.issue-evidence-dialog > h3 { margin-top: 20px; }
.issue-evidence-dialog p, .source-evidence { overflow-wrap: anywhere; white-space: pre-wrap; }
.page-evidence { margin: 16px 0; }
blockquote { margin: 12px 0; padding: 12px 16px; background: var(--canvas); border-left: 3px solid var(--brand); }
blockquote p { margin-bottom: 8px; }
blockquote small { color: var(--muted); }
.review-form { margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--line); }
.review-form fieldset { padding: 0; border: 0; min-width: 0; }
.review-actions { display: flex; flex-wrap: wrap; gap: 12px; justify-content: space-between; align-items: center; }
@media (max-width: 600px) { .compared-check dl { grid-template-columns: 1fr; } .review-actions { align-items: stretch; flex-direction: column; } }
</style>
