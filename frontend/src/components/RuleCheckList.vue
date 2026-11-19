<script setup lang="ts">
import { computed, getCurrentInstance, ref, watch } from 'vue'
import type { RuleCheck } from '../types'
import { displayLocation, displayRuleEvidence, displaySource, ruleLabel, sourceEntries } from '../utils/report'
import StatusBadge from './StatusBadge.vue'
import ListPagination from './ListPagination.vue'
import AppIcon from './AppIcon.vue'
import { usePagedItems } from '../composables/usePagedItems'

const props = defineProps<{ checks: RuleCheck[]; complete?: boolean; identity?: string }>()
const filter = ref('all'), expanded = ref<number>()
const prefix = `rule-check-${getCurrentInstance()!.uid}`
const statuses = [
  { value: 'all', label: '全部检查' }, { value: 'passed', label: '通过' }, { value: 'failed', label: '不符合' },
  { value: 'manual', label: '待复核' }, { value: 'not_checked', label: '未执行' },
  { value: 'unsupported', label: '不支持' }, { value: 'error', label: '检查失败' }, { value: 'not_applicable', label: '已排除' }
]
const filtered = computed(() => props.checks.filter(check => filter.value === 'all' || check.status === filter.value))
const { page, displayed: paged, setPage } = usePagedItems(filtered, 10, false)
const displayed = computed(() => props.complete ? props.checks : paged.value)
// An explicit identity distinguishes a refreshed collection from another report.
watch(() => props.checks, () => { if (props.identity === undefined) setPage(1); expanded.value = undefined }, { flush: 'sync' })
watch([filter, () => props.identity], () => setPage(1), { flush: 'sync' })
watch([filter, page], () => { expanded.value = undefined }, { flush: 'sync' })
const label = (status?: string) => statuses.find(item => item.value === status)?.label || '状态未记录'
function explanations(check: RuleCheck) {
  const title = check.label || check.message || ruleLabel(check.target || check.rule_id)
  const exclusion = check.exclusion_reason?.trim()
  return [...new Set([check.reason, check.message].map(value => value?.trim()).filter((value): value is string =>
    !!value && value !== title && (!exclusion || ![exclusion, `已确认排除：${exclusion}`, `排除理由：${exclusion}`].includes(value))))]
}
</script>
<template>
  <div class="rule-check-list">
    <div v-if="!complete" class="filter-chips" role="group" aria-label="筛选检查状态"><button v-for="item in statuses" :key="item.value" type="button" class="filter-chip" :class="{ active: filter === item.value }" :aria-pressed="filter === item.value" @click="filter = item.value">{{ item.label }}</button></div>
    <p class="field-help check-count" role="status">本页 {{ displayed.length }} 项，共 {{ complete ? checks.length : filtered.length }} 项</p>
    <div :class="{ 'rule-check-scroll': !complete }" :tabindex="complete ? undefined : 0" :role="complete ? undefined : 'region'" :aria-label="complete ? undefined : '当前页规则检查'">
    <article v-for="(check, index) in displayed" :key="`${check.rule_id}-${index}`" class="check-card">
      <button v-if="!complete" type="button" class="check-summary" :aria-expanded="expanded === index" :aria-controls="`${prefix}-${index}`" @click="expanded = expanded === index ? undefined : index"><StatusBadge :status="check.status" :label="label(check.status)" /><span><strong>{{ check.label || check.message || ruleLabel(check.target || check.rule_id) }}</strong><small v-if="check.location">{{ displayLocation(check.location) }}</small></span><span class="check-disclosure" aria-hidden="true">{{ expanded === index ? '收起' : '详情' }}<AppIcon name="chevron-right" :class="{ rotated: expanded === index }" /></span></button>
      <div v-else class="issue-title-row"><StatusBadge :status="check.status" :label="label(check.status)" /><h3>{{ check.label || check.message || ruleLabel(check.target || check.rule_id) }}</h3></div>
      <div v-if="complete || expanded === index" :id="`${prefix}-${index}`" class="check-details">
      <p v-if="complete && check.location" class="issue-location">{{ displayLocation(check.location) }}</p>
      <div class="issue-detail"><div><span class="issue-detail-label">要求格式</span><div class="issue-detail-value">{{ displayRuleEvidence(check.expected, check.target || check.rule_id) }}</div></div><div><span class="issue-detail-label">实际格式与证据</span><div class="issue-detail-value">{{ displayRuleEvidence(check.actual, check.target || check.rule_id) }}</div></div></div>
      <p v-for="explanation in explanations(check)" :key="explanation" class="field-help">{{ explanation }}</p>
      <p v-if="check.exclusion_reason?.trim()" class="notice neutral-notice"><strong>排除理由：</strong>{{ check.exclusion_reason }}</p>
      <p v-else-if="check.excluded || check.status === 'not_applicable'" class="notice warm-notice">未记录排除理由，请核对方案。</p>
      <p v-for="(source, sourceIndex) in sourceEntries(check.source)" :key="sourceIndex" class="issue-source">依据：{{ displaySource(source) }}</p>
      <details v-if="check.rule_id || check.plugin || typeof check.expected === 'object' || typeof check.actual === 'object'" class="check-technical"><summary>原始检测证据</summary><p v-if="check.rule_id">规则编号：{{ check.rule_id }}</p><p v-if="check.plugin">组件编号：{{ check.plugin }}</p><p v-if="check.location">原始位置：{{ check.location }}</p><pre v-if="typeof check.expected === 'object' || typeof check.actual === 'object'" class="evidence-block">{{ JSON.stringify({ expected: check.expected, actual: check.actual }, null, 2) }}</pre></details>
      </div>
    </article>
    </div>
    <p v-if="!filtered.length" class="empty-state">没有此状态的检查项</p>
    <ListPagination v-if="!complete" :page="page" :total="filtered.length" label="规则检查分页" @change="setPage" />
  </div>
</template>
<style scoped>
.rule-check-scroll { max-height: min(58vh, 620px); overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; border-top: 1px solid var(--line); }
.rule-check-scroll .check-card { padding: 0; border: 0; border-bottom: 1px solid var(--line); }
.check-count { margin-block: 16px; font-size: 14px; }
.check-summary { display: flex; gap: 14px; align-items: center; width: 100%; text-align: left; border: 0; border-radius: 8px; background: transparent; color: inherit; padding: 18px 12px; cursor: pointer; }
.check-summary:hover { background: var(--canvas); }
.check-summary > span:nth-child(2) { flex: 1; min-width: 0; }
.check-summary strong { font-size: 16px; font-weight: 600; overflow-wrap: anywhere; }
.check-summary small { display: block; color: var(--muted); font-size: 14px; margin-top: 4px; overflow-wrap: anywhere; }
.check-summary:focus-visible, .rule-check-scroll:focus-visible { outline: 3px solid var(--brand-strong); outline-offset: -3px; }
.check-disclosure { display: inline-flex; align-items: center; gap: 4px; color: var(--muted); font-size: 13px; flex-shrink: 0; }
.check-disclosure svg { width: 16px; height: 16px; transition: transform .15s ease; }
.check-disclosure .rotated { transform: rotate(90deg); }
.check-details { padding: 0 12px 20px; }
.issue-detail { gap: 12px; margin-top: 0; }
.issue-detail > div { padding: 14px 16px; background: var(--canvas); border: 1px solid var(--line); border-radius: 8px; }
.issue-detail-label { font-size: 13px; color: var(--muted); }
.issue-detail-value { margin-top: 8px; padding: 0; background: transparent; color: var(--ink); font: inherit; font-size: 15px; line-height: 1.65; }
.issue-source { font-size: 14px; color: var(--muted); margin-top: 12px; }
.check-technical { margin-top: 12px; padding-top: 4px; border-top: 1px dashed var(--line); font-size: 14px; color: var(--muted); overflow-wrap: anywhere; }
.check-technical summary { cursor: pointer; min-height: 44px; padding-block: 10px; }
@media (max-width: 480px) { .check-summary { flex-wrap: wrap; padding: 16px 4px; gap: 10px; align-items: flex-start; } .check-summary > span:nth-child(2) { flex-basis: calc(100% - 100px); } .check-disclosure { margin-left: auto; } .check-details { padding-inline: 4px; } .issue-detail { grid-template-columns: 1fr; } .issue-detail > div { padding: 12px; } }
@media (prefers-reduced-motion: reduce) { .check-disclosure svg { transition: none; } }
</style>
