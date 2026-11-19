<script setup lang="ts">
import { computed, getCurrentInstance, h, nextTick, ref, watch } from 'vue'
import type { Engine, Result } from '../types'
import { displayEvidence, engineLabel } from '../utils/report'
import { profileLabel } from '../utils/materials'
import IssueCard from './IssueCard.vue'
import StatusBadge from './StatusBadge.vue'
import RuleCheckList from './RuleCheckList.vue'
import DocumentExtraction from './DocumentExtraction.vue'
import AppIcon from './AppIcon.vue'
import { displayCount } from '../utils/numbers'
import { useReportIssues } from '../composables/useReportIssues'
import { useCompleteReportPrint } from '../composables/useCompleteReportPrint'

const props = defineProps<{ result: Result; canLocateOcr?: boolean; completePrint?: boolean }>()
const emit = defineEmits<{ locateOcr: [string] }>()
const issuesHeading = ref<HTMLElement>()
const printHost = ref<Element>()
const instance = getCurrentInstance()!
const tabs = [{ id: 'issues', label: '问题明细' }, { id: 'checks', label: '规则检查' }, { id: 'document', label: '文档信息' }, { id: 'details', label: instance.slots.repair ? '修复与报告' : '方案与记录' }]
const activeTab = ref('issues'), tabButtons = ref<HTMLButtonElement[]>([])
const expandedIssue = ref<number>()
const tabId = (id: string) => `report-${instance.uid}-${id}`
function switchTab(id: string) { activeTab.value = id }
async function tabKey(event: KeyboardEvent, index: number) {
  let selected: number
  if (event.key === 'ArrowRight') selected = (index + 1) % tabs.length
  else if (event.key === 'ArrowLeft') selected = (index + tabs.length - 1) % tabs.length
  else if (event.key === 'Home') selected = 0
  else if (event.key === 'End') selected = tabs.length - 1
  else return
  event.preventDefault(); activeTab.value = tabs[selected]!.id
  await nextTick(); tabButtons.value[selected]?.focus?.()
}
const printer = props.completePrint ? undefined : useCompleteReportPrint(printHost, () => {
  const node = h(instance.type, { result: props.result, completePrint: true })
  node.appContext = instance.appContext
  return node
})
const filters = [
  { value: 'all', label: '全部' },
  { value: 'error', label: '错误' },
  { value: 'warning', label: '风险提示' },
  { value: 'manual', label: '人工复核' }
]
const counts = computed(() => props.result.document_counts || props.result.counts || {})
const coverage = computed(() => props.result.coverage)
const snapshot = computed(() => props.result.profile_snapshot)
const allIssues = computed(() => props.result.issues || [])
const { level, search, page, pageCount, filtered: issues, visible: visibleIssues, start, end, setPage } = useReportIssues(allIssues, computed(() => !!props.completePrint))
watch([page, level, search, allIssues], () => { expandedIssue.value = undefined }, { flush: 'sync' })
async function showIssues(filter: string) {
  activeTab.value = 'issues'
  level.value = filter
  search.value = ''
  await nextTick()
  issuesHeading.value?.focus({ preventScroll: true })
  issuesHeading.value?.scrollIntoView({ block: 'start' })
}
async function changePage(value: number) { setPage(value); await nextTick(); issuesHeading.value?.focus({ preventScroll: true }); issuesHeading.value?.scrollIntoView({ block: 'start' }) }
const verdict = computed(() => ({
  passed: '已检查范围内未发现问题',
  needs_changes: '发现格式问题',
  review_required: '有待复核事项',
  incomplete: '检测未完成'
}[props.result.status || ''] || '检测结果已生成'))
const engines = computed<Engine[]>(() => {
  const value = props.result.engines
  return Array.isArray(value) ? value : Object.entries(value || {}).map(([id, engine]) => ({ id, ...engine }))
})
</script>

<template>
  <div class="report-container">
  <div class="report-content" :class="{ 'report-screen-copy': !completePrint }">
    <div class="report-overview" :class="`overview-${result.status || 'unknown'}`">
    <div class="verdict-banner">
      <span class="verdict-icon" :class="`verdict-${result.status || 'unknown'}`" aria-hidden="true"><AppIcon :name="result.status === 'passed' ? 'check' : 'alert'" /></span>
      <div>
        <strong>{{ verdict }}</strong>
        <p v-if="result.status === 'review_required'" class="verdict-note">自动检查已经结束。签章、版式和未绑定范围仍需人工复核，不记为自动通过。</p>
      </div>
    </div>

    <div class="result-stats">
      <button type="button" class="result-stat error-stat" :aria-pressed="level === 'error'" @click="showIssues('error')">
        <span>文档偏差</span><strong :title="String(counts.error || 0)" :aria-label="String(counts.error || 0)">{{ displayCount(counts.error || 0) }}</strong><small v-if="!result.document_counts">含执行异常</small>
      </button>
      <button type="button" class="result-stat warning-stat" :aria-pressed="level === 'warning'" @click="showIssues('warning')">
        <span>风险提示</span><strong :title="String(counts.warning || 0)" :aria-label="String(counts.warning || 0)">{{ displayCount(counts.warning || 0) }}</strong>
      </button>
      <button type="button" class="result-stat manual-stat" :aria-pressed="level === 'manual'" @click="showIssues('manual')">
        <span>人工复核</span><strong :title="String(counts.manual || 0)" :aria-label="String(counts.manual || 0)">{{ displayCount(counts.manual || 0) }}</strong>
      </button>
    </div>
    </div>

    <p v-if="result.execution_errors" class="notice error-notice" role="alert">执行或完整性异常 {{ result.execution_errors }} 项，请查看执行记录。</p>
    <div v-if="!completePrint" class="report-section-bar">
      <div class="report-tabs" role="tablist" aria-label="报告内容">
        <button v-for="(tab, index) in tabs" :id="tabId(tab.id)" :key="tab.id" :ref="element => { if (element) tabButtons[index] = element as HTMLButtonElement }" type="button" role="tab" :aria-selected="activeTab === tab.id" :aria-controls="`${tabId(tab.id)}-panel`" :tabindex="activeTab === tab.id ? 0 : -1" @click="switchTab(tab.id)" @keydown="tabKey($event, index)">{{ tab.label }}</button>
      </div>
      <button type="button" class="text-button report-print-action" @click="printer?.print()"><AppIcon name="file" />打印完整报告</button>
    </div>
    <section v-if="completePrint || activeTab === 'issues'" :id="`${tabId('issues')}-panel`" class="panel issues-panel report-tab-panel" :role="completePrint ? undefined : 'tabpanel'" :aria-labelledby="completePrint ? undefined : tabId('issues')">
      <div class="panel-heading"><h2 ref="issuesHeading" tabindex="-1" class="issues-heading">问题与证据</h2><span class="muted micro" role="status">共 {{ completePrint ? allIssues.length : issues.length }} 条</span></div>
      <div v-if="!completePrint" class="table-toolbar issues-toolbar">
        <div class="filter-chips">
          <button v-for="filter in filters" :key="filter.value" :aria-pressed="level === filter.value" class="filter-chip" :class="{ active: level === filter.value }" type="button" @click="level = filter.value">{{ filter.label }}</button>
        </div>
        <label class="search-field"><AppIcon name="search" /><input v-model="search" type="search" placeholder="搜索规则、位置或说明" aria-label="搜索问题" /></label>
      </div>
      <div v-if="visibleIssues.length" class="report-issue-list" :class="{ 'report-issue-scroll': !completePrint }" :tabindex="completePrint ? undefined : 0" :role="completePrint ? undefined : 'region'" :aria-label="completePrint ? undefined : '当前页问题列表'"><IssueCard v-for="entry in visibleIssues" :key="entry.index" :issue="entry.issue" :issue-key="completePrint ? `print-${entry.index}` : entry.index" :compact="!completePrint" :expanded="expandedIssue === entry.index" @toggle="expandedIssue = expandedIssue === entry.index ? undefined : entry.index"><template v-if="$slots['issue-actions'] && !completePrint" #actions><slot name="issue-actions" :index="entry.index" /></template></IssueCard></div>
      <p v-else class="empty-state">没有匹配的问题</p>
      <nav v-if="!completePrint && pageCount > 1" class="issue-pagination" aria-label="问题分页">
        <span role="status">第 {{ start }}–{{ end }} 条</span>
        <div class="issue-page-controls"><button type="button" class="button secondary" :disabled="page === 1" @click="changePage(page - 1)">上一页</button>
        <label><span class="visually-hidden">页码</span><input type="number" :value="page" min="1" :max="pageCount" aria-label="问题页码" @change="changePage(Number(($event.target as HTMLInputElement).value))" /> / {{ pageCount }}</label>
        <button type="button" class="button secondary" :disabled="page === pageCount" @click="changePage(page + 1)">下一页</button></div>
      </nav>
    </section>

    <section v-if="completePrint || activeTab === 'checks'" :id="`${tabId('checks')}-panel`" class="panel coverage-panel report-tab-panel" :role="completePrint ? undefined : 'tabpanel'" :aria-labelledby="completePrint ? undefined : tabId('checks')">
      <div class="panel-heading"><h2>规则检查</h2><span class="muted micro">格式检查 {{ coverage?.format_checks ?? '未记录' }} 次</span></div>
      <p v-if="coverage?.complete === false && !coverage.summary" class="field-help">检查尚未完成。</p>
      <div v-if="coverage?.summary" class="coverage-summary"><span>通过 {{ coverage.summary.passed || 0 }}</span><span>不符合 {{ coverage.summary.failed || 0 }}</span><span>待复核 {{ coverage.summary.manual || 0 }}</span><span>未执行 {{ coverage.summary.not_checked || 0 }}</span><span>不支持 {{ coverage.summary.unsupported || 0 }}</span><span>检查失败 {{ coverage.summary.error || 0 }}</span><span>已排除 {{ coverage.summary.not_applicable || 0 }}</span></div>
      <RuleCheckList v-if="coverage?.checks?.length" :checks="coverage.checks" :complete="completePrint" />
      <p v-else class="notice warm-notice">未记录逐项检查，无法确认检测覆盖范围。</p>
    </section>
    <section v-if="completePrint || activeTab === 'document'" :id="`${tabId('document')}-panel`" class="panel document-info-panel report-tab-panel" :role="completePrint ? undefined : 'tabpanel'" :aria-labelledby="completePrint ? undefined : tabId('document')">
      <div class="panel-heading"><h2>文档信息</h2></div>
      <DocumentExtraction :format="result.input_format" :extraction="result.document_extraction" :can-locate-ocr="canLocateOcr" :complete="completePrint" @locate-ocr="emit('locateOcr', $event)" />
    </section>

    <div v-show="completePrint || activeTab === 'details'" :id="`${tabId('details')}-panel`" class="report-tab-panel" :role="completePrint ? undefined : 'tabpanel'" :aria-labelledby="completePrint ? undefined : tabId('details')">
    <slot name="repair" />
    <section v-if="result.repair" class="panel repair-summary">
      <div class="panel-heading"><h2>修复记录</h2></div>
      <p>原文档：{{ result.repair.source_filename || '名称未记录' }}</p>
      <p>已应用 {{ result.repair.applied_count }} 项格式修改。</p>
      <p v-if="result.repair.dropped_paired_pdf" class="field-help">原配对 PDF 未用于复检。</p>
    </section>
    <div class="result-bottom-grid">
      <section class="panel">
        <div class="panel-heading"><h2>执行情况</h2></div>
        <div class="engine-list">
          <div v-for="engine in engines" :key="engine.id" class="engine-evidence">
            <div class="engine-row"><div>
              <strong>{{ engineLabel(engine.id, engine.name) }}</strong>
              <small>{{ typeof engine.duration_ms === 'number' ? `${(engine.duration_ms / 1000).toFixed(2)} 秒` : '耗时未记录' }}<span v-if="engine.error"> · {{ displayEvidence(engine.error) }}</span></small>
            </div>
            <StatusBadge :status="engine.status" /></div>
            <details v-if="engine.evidence !== undefined" :open="completePrint"><summary>技术记录</summary><pre class="evidence-block">{{ displayEvidence(engine.evidence) }}</pre></details>
            <details v-if="engine.id"><summary>组件编号</summary><p>{{ engine.id }}</p></details>
          </div>
          <p v-if="!engines.length" class="empty-state">暂无执行记录</p>
        </div>
      </section>
      <section class="panel report-integrity-panel">
        <div class="panel-heading"><h2>文件完整性</h2></div>
        <p>{{ result.input_unchanged === true ? '输入快照未变化。' : '输入快照完整性未确认。' }}</p>
        <p v-if="result.original_unchanged !== undefined">{{ result.original_unchanged ? '原文件未变化。' : '原文件发生变化或已不可读。' }}</p>
        <p v-if="result.pdf_sha256">{{ result.pdf_unchanged === true ? 'PDF 快照未变化。' : 'PDF 快照完整性未确认。' }}</p>
        <p v-if="result.original_pdf_unchanged !== undefined">{{ result.original_pdf_unchanged ? 'PDF 原件未变化。' : 'PDF 原件发生变化或已不可读。' }}</p>
        <details class="report-details" :open="completePrint"><summary>校验信息</summary><span class="issue-detail-label">原稿校验摘要</span><div class="issue-detail-value">{{ result.input_sha256 || '未记录' }}</div><template v-if="result.pdf_sha256"><span class="issue-detail-label">配对文件校验摘要</span><div class="issue-detail-value">{{ result.pdf_sha256 }}</div></template></details>
      </section>
    </div>
    <section class="panel snapshot-panel">
      <div class="panel-heading"><h2>检测方案</h2></div>
      <p v-if="snapshot">{{ profileLabel(snapshot) }}</p>
      <p v-else class="notice warm-notice">未保存方案快照，请核对方案附件。</p>
      <details v-if="snapshot?.school" :open="completePrint"><summary>学校依据与版本</summary><pre class="evidence-block">{{ displayEvidence(snapshot.school) }}</pre></details>
      <details v-if="snapshot || result.profile_sha256 || result.profile_id" :open="completePrint"><summary>方案技术信息</summary><p>方案编号：{{ snapshot?.id || result.profile_id || '未记录' }}</p><div v-if="result.profile_sha256" class="issue-detail-value">规则校验摘要：{{ result.profile_sha256 }}</div><pre v-if="snapshot" class="evidence-block">{{ displayEvidence(snapshot) }}</pre></details>
    </section>
    <slot name="details" />
    </div>
  </div>
  <div v-if="!completePrint" ref="printHost" class="report-print-copy" />
  </div>
</template>

<style scoped>
.report-content {
  min-width: 0;
}
.report-overview { display: grid; grid-template-columns: minmax(220px, 1fr) minmax(0, 1.2fr); align-items: center; gap: 24px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); margin-bottom: 24px; padding: 24px; }
.verdict-banner { padding: 0; border: 0; border-radius: 0; background: transparent; margin: 0; gap: 14px; }
.verdict-banner strong { font-size: 20px; font-weight: 650; line-height: 1.5; }
.verdict-note { margin: 4px 0 0; color: var(--muted); font-size: 13px; line-height: 1.5; }
.verdict-icon { border-radius: 10px; width: 44px; height: 44px; }
.verdict-icon svg { width: 22px; height: 22px; }
.result-stats { gap: 0; margin: 0; }
.result-stat { position: relative; border: 0; border-left: 1px solid var(--line); border-radius: 0; background: transparent; padding: 4px 20px; min-height: 78px; gap: 4px; }
.result-stat span { color: var(--muted); font-size: 14px; white-space: nowrap; }
.result-stat strong { font-size: 30px; font-weight: 650; font-variant-numeric: tabular-nums; }
.result-stat small { font-size: 12px; }
.result-stat.error-stat, .result-stat.warning-stat, .result-stat.manual-stat { border-color: var(--line); }
.result-stat:hover, .result-stat[aria-pressed="true"] { background: var(--canvas); }
.result-stat[aria-pressed="true"]::after { content: ''; position: absolute; bottom: -8px; left: 20px; right: 20px; height: 2px; background: var(--brand); }
.error-stat strong { color: var(--danger); }
.warning-stat strong { color: var(--warning); }
.manual-stat strong { color: var(--review); }
.report-print-copy { display: none; }
.report-section-bar { display: flex; align-items: center; flex-wrap: wrap; justify-content: space-between; gap: 12px; margin-block: 20px; border-bottom: 1px solid var(--line); }
.report-tabs { display: flex; flex: 1; min-width: 0; flex-wrap: wrap; gap: 20px; }
.report-tabs button { padding: 14px 2px; min-height: 48px; margin-bottom: -1px; border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: transparent; color: var(--muted); font-size: 15px; font-weight: 600; cursor: pointer; }
.report-tabs button:hover { color: var(--ink); }
.report-tabs button[aria-selected="true"] { border-bottom-color: var(--brand); background: transparent; color: var(--brand); }
.report-print-action { display: inline-flex; align-items: center; gap: 7px; font-size: 14px; }
.report-tabs button:focus-visible, .report-issue-scroll:focus-visible { outline: 3px solid var(--brand-strong); outline-offset: 3px; }
.report-tab-panel { min-width: 0; }
.issues-panel { padding: 24px; }
.issues-panel > .panel-heading { padding-top: 0; margin-bottom: 18px; }
.issues-toolbar { gap: 16px; padding: 0 0 20px; margin: 0; align-items: center; }
.issues-toolbar .search-field { max-width: 320px; }
.report-issue-scroll { max-height: min(58vh, 620px); overflow-y: auto; overscroll-behavior: contain; padding: 0 3px 0 0; scrollbar-gutter: stable; border-top: 1px solid var(--line); }
.report-issue-scroll :deep(.issue-card:last-child) { margin-bottom: 0; }
.issue-pagination { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin: 20px 0 0; padding-top: 16px; border-top: 1px solid var(--line); font-size: 14px; color: var(--muted); }
.issue-page-controls, .issue-pagination label { display: flex; align-items: center; gap: 8px; min-width: 0; }
.issue-page-controls { flex-wrap: wrap; }
.issue-pagination label { flex: none; white-space: nowrap; }
.issue-pagination input { width: 60px; min-height: 44px; padding: 8px; border: 1px solid var(--line-strong); border-radius: 8px; background: var(--surface); color: var(--ink); font-size: 15px; text-align: center; }
.issue-pagination .button { padding-inline: 14px; }
.coverage-summary { gap: 8px 16px; padding: 12px 16px; background: var(--canvas); border: 1px solid var(--line); border-radius: 8px; font-size: 14px; }
@media print {
  .report-screen-copy { display: none !important; }
  .report-print-copy { display: block !important; }
  .report-print-copy :deep(.panel) { break-inside: auto; box-shadow: none; }
  .report-print-copy :deep(.issue-card), .report-print-copy :deep(.check-card) { break-inside: avoid; }
  .report-print-copy :deep(.result-bottom-grid) { grid-template-columns: 1fr; }
  .report-overview { break-inside: avoid; grid-template-columns: 1fr; gap: 16px; }
}

.issues-heading {
  scroll-margin-top: calc(var(--topbar-height, 0px) + 20px);
}

.issues-heading:focus-visible {
  outline: 3px solid var(--brand-strong);
  outline-offset: 4px;
  border-radius: 4px;
}

.repair-summary,
.document-info-panel {
  min-width: 0;
  margin-bottom: 20px;
  padding: var(--panel-padding, 22px);
}

.repair-summary p {
  margin-bottom: 8px;
  overflow-wrap: anywhere;
}

.repair-summary p:last-child {
  margin-bottom: 0;
}

.report-integrity-panel p {
  color: var(--muted);
  font-size: 14px;
  overflow-wrap: anywhere;
}

.report-details > summary {
  min-height: 44px;
  padding-block: 10px;
  color: var(--brand);
  font-size: 15px;
  cursor: pointer;
  overflow-wrap: anywhere;
}

.report-details > summary:focus-visible {
  outline: 3px solid var(--brand-strong);
  outline-offset: 3px;
  border-radius: 6px;
}

@media (max-width: 767px) {
  .report-overview { grid-template-columns: 1fr; gap: 20px; padding: 20px; }
  .verdict-banner strong { font-size: 18px; }
  .result-stat { padding: 0 8px; min-height: 66px; }
  .result-stat:first-child { padding-left: 0; border-left: 0; }
  .result-stat strong { font-size: 26px; }
  .result-stat[aria-pressed="true"]::after { left: 8px; right: 8px; }
  .report-section-bar { gap: 0; }
  .report-tabs { flex-basis: 100%; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
  .report-tabs button { padding: 12px 4px; text-align: center; }
  .report-print-action { margin-left: auto; }
  .issues-panel { padding: 18px; }
  .issues-toolbar .search-field { max-width: none; }
  .issue-pagination { gap: 12px; }
  .issue-page-controls { flex: 1 1 100%; justify-content: space-between; }
  .issue-pagination .button { padding-inline: 10px; font-size: 14px; }
  .issue-pagination input { width: 52px; }
  .repair-summary,
  .document-info-panel {
    padding: var(--panel-padding, 18px);
  }
}

@container workspace (max-width: 1000px) { .report-overview { grid-template-columns: 1fr; gap: 20px; } .result-stat:first-child { border-left: 0; padding-left: 0; } }

@container workspace (max-width: 600px) {
  .repair-summary,
  .document-info-panel {
    padding: var(--panel-padding, 18px);
  }
}
</style>
