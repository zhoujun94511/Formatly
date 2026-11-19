<script setup lang="ts">
import type { Issue } from '../types'
import StatusBadge from './StatusBadge.vue'
import AppIcon from './AppIcon.vue'
import { displayLocation, displayRuleEvidence, displaySource, issueTitle, sourceEntries } from '../utils/report'
defineProps<{ issue: Issue; issueKey?: string | number; compact?: boolean; expanded?: boolean }>()
defineEmits<{ toggle: [] }>()
</script>

<template>
  <article class="issue-card" :class="{ 'issue-card-compact': compact, 'issue-card-expanded': !compact || expanded }" :aria-labelledby="`issue-title-${issueKey ?? issue.rule_id ?? 'item'}`">
    <button v-if="compact" class="issue-summary" type="button" :aria-expanded="!!expanded" :aria-controls="`issue-details-${issueKey}`" @click="$emit('toggle')">
      <StatusBadge :status="issue.level" />
      <span class="issue-summary-text"><strong :id="`issue-title-${issueKey}`">{{ issueTitle(issue) }}</strong><span class="issue-summary-location">{{ displayLocation(issue.location) }}</span></span>
      <span class="issue-disclosure" aria-hidden="true">{{ expanded ? '收起' : '详情' }}<AppIcon name="chevron-right" :class="{ rotated: expanded }" /></span>
    </button>
    <template v-else>
      <div class="issue-title-row"><StatusBadge :status="issue.level" /><h3 :id="`issue-title-${issueKey ?? issue.rule_id ?? 'item'}`">{{ issueTitle(issue) }}</h3></div>
      <p class="issue-location">{{ displayLocation(issue.location) }}</p>
    </template>
    <div v-if="!compact || expanded" :id="`issue-details-${issueKey}`" class="issue-expanded-content">
      <div v-if="issue.expected !== undefined || issue.actual !== undefined" class="issue-detail">
        <div><span class="issue-detail-label">要求格式</span><div class="issue-detail-value">{{ displayRuleEvidence(issue.expected, issue.rule_id) }}</div></div>
        <div><span class="issue-detail-label">实际格式</span><div class="issue-detail-value">{{ displayRuleEvidence(issue.actual, issue.rule_id) }}</div></div>
      </div>
      <p v-for="(source, index) in sourceEntries(issue.source)" :key="index" class="issue-source">依据：{{ displaySource(source) }}</p>
      <div v-if="$slots.actions" class="issue-actions"><slot name="actions" /></div>
      <details v-if="issue.rule_id || issue.plugin || typeof issue.expected === 'object' || typeof issue.actual === 'object'" class="issue-technical"><summary>原始检测证据</summary><p v-if="issue.rule_id">规则编号：{{ issue.rule_id }}</p><p v-if="issue.plugin">组件编号：{{ issue.plugin }}</p><p v-if="issue.location">原始位置：{{ issue.location }}</p><pre v-if="typeof issue.expected === 'object' || typeof issue.actual === 'object'" class="evidence-block">{{ JSON.stringify({ expected: issue.expected, actual: issue.actual }, null, 2) }}</pre></details>
    </div>
  </article>
</template>

<style scoped>
.issue-card-compact { padding: 0; margin-bottom: 0; border-top: 0; border-bottom: 1px solid var(--line); }
.issue-card-expanded { background: var(--surface); }
.issue-summary { display: flex; width: 100%; gap: 14px; align-items: center; padding: 18px 12px; text-align: left; border: 0; border-radius: 8px; background: transparent; color: inherit; cursor: pointer; }
.issue-summary:hover { background: var(--canvas); }
.issue-summary:focus-visible { outline: 3px solid var(--brand-strong); outline-offset: -3px; }
.issue-summary-text { flex: 1; min-width: 0; }
.issue-summary-text strong { display: block; font-size: 16px; font-weight: 600; overflow-wrap: anywhere; }
.issue-summary-location { display: block; color: var(--muted); font-size: 14px; margin-top: 4px; overflow-wrap: anywhere; }
.issue-disclosure { display: inline-flex; align-items: center; gap: 4px; flex-shrink: 0; color: var(--muted); font-size: 13px; }
.issue-disclosure svg { width: 16px; height: 16px; transition: transform .15s ease; }
.issue-disclosure .rotated { transform: rotate(90deg); }
.issue-card-compact .issue-expanded-content { padding: 0 12px 20px; }
.issue-detail { gap: 12px; margin-top: 4px; }
.issue-detail > div { padding: 14px 16px; background: var(--canvas); border: 1px solid var(--line); border-radius: 8px; }
.issue-detail-label { font-size: 13px; color: var(--muted); }
.issue-detail-value { margin-top: 8px; padding: 0; background: transparent; color: var(--ink); font: inherit; font-size: 15px; line-height: 1.65; }
.issue-source { margin-top: 12px; color: var(--muted); font-size: 14px; }
.issue-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding-top: 8px; }
.issue-technical { margin-top: 12px; padding-top: 4px; border-top: 1px dashed var(--line); color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }
.issue-technical summary { cursor: pointer; min-height: 44px; padding-block: 10px; }
@media (max-width: 480px) { .issue-summary { gap: 10px; padding: 16px 4px; align-items: flex-start; flex-wrap: wrap; } .issue-summary-text { flex-basis: calc(100% - 100px); } .issue-disclosure { margin-left: auto; } .issue-card-compact .issue-expanded-content { padding-inline: 4px; } .issue-detail { grid-template-columns: 1fr; } .issue-detail > div { padding: 12px; } }
@media (prefers-reduced-motion: reduce) { .issue-disclosure svg { transition: none; } }
</style>

