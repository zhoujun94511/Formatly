<script setup lang="ts">
import { computed } from 'vue'
import type { EffectiveSummary, ExpectedCapability } from '../utils/profileFields'
import { displayEvidence } from '../utils/report'
import { usePagedItems } from '../composables/usePagedItems'
import ListPagination from './ListPagination.vue'

const props = defineProps<{ summary: EffectiveSummary }>()
const items = computed(() => props.summary.items)
const { page, displayed, setPage } = usePagedItems(items)
const labels: Record<ExpectedCapability, string> = { conditional: '预计可检查', manual: '需复核', unsupported: '格式不支持', excluded: '已排除', unavailable: '能力不可用' }
</script>
<template>
  <details class="profile-summary">
    <summary>本次规则范围 <span>{{ summary.counts.conditional }} 项预计可检查<span v-if="summary.counts.manual"> · {{ summary.counts.manual }} 项需复核</span><span v-if="summary.counts.unsupported"> · {{ summary.counts.unsupported }} 项不支持</span></span></summary>
    <p class="field-help">{{ summary.profile_name }} · v{{ summary.version }} · {{ summary.source.name }}</p>
    <p v-if="!summary.items.length" class="notice warm-notice">尚未配置可展示的格式规则，请核对方案内容。</p>
    <div v-if="items.length" class="capability-scroll" tabindex="0" role="region" aria-label="本次规则范围列表">
      <ul class="capability-items"><li v-for="(item, index) in displayed" :key="`${item.target}-${(page - 1) * 10 + index}`"><strong>{{ item.label }}</strong><span>{{ labels[item.state] }}<template v-if="item.expected !== undefined"> · {{ displayEvidence(item.expected) }}</template></span><small>{{ item.reason }}<template v-if="item.scope">；范围：{{ displayEvidence(item.scope) }}</template></small></li></ul>
    </div>
    <ListPagination :page="page" :total="items.length" label="规则范围分页" @change="setPage" />
    <p class="field-help">{{ summary.disclaimer }}</p>
  </details>
</template>
<style scoped>
.profile-summary { margin-block: 14px; border-top: 1px solid var(--line); }
summary { cursor: pointer; padding-block: 12px; min-height: 44px; font-size: 15px; font-weight: 700; }
summary > span { display: block; margin-top: 4px; font-weight: 400; color: var(--muted); }
summary:focus-visible { outline: 3px solid var(--brand); outline-offset: 2px; }
.capability-scroll { max-height: min(360px, 45vh); overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; padding-inline: 2px 8px; }
.capability-items { list-style: none; margin: 0; padding: 0; }
li { display: grid; gap: 4px; padding-block: 12px; border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
li:last-child { border-bottom: 0; }
li > span, small { font-size: 14px; color: var(--muted); }
</style>
