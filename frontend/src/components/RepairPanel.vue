<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { Job } from '../types'
import { useDocumentRepair } from '../composables/useDocumentRepair'
import { displayRuleEvidence, displayLocation } from '../utils/report'
import ListPagination from './ListPagination.vue'
import AppIcon from './AppIcon.vue'
import { usePagedItems } from '../composables/usePagedItems'

const props = defineProps<{ job: Job; disabled?: boolean }>()
const emit = defineEmits<{ repaired: [Job]; busy: [boolean] }>()
const repair = useDocumentRepair(() => props.job)
const { plan, selectedIds, loading, saving, error, eligible, canSubmit, createdJob } = repair
const previewHeading = ref<HTMLElement>()
const candidates = computed(() => plan.value?.candidates || [])
const skipped = computed(() => plan.value?.skipped || [])
const { page, displayed, setPage } = usePagedItems(candidates)
const { page: skippedPage, displayed: displayedSkipped, setPage: setSkippedPage } = usePagedItems(skipped)
const frozen = computed(() => !!props.disabled || loading.value || saving.value || !!createdJob.value)
watch(saving, value => emit('busy', value), { flush: 'sync', immediate: true })
onBeforeUnmount(() => emit('busy', false))

async function preview() {
  if (props.disabled) return
  await repair.preview()
  if (plan.value) { await nextTick(); previewHeading.value?.focus() }
}
async function apply() {
  if (props.disabled) return
  const result = await repair.apply()
  if (result) emit('repaired', result)
}
</script>

<template>
  <section class="panel repair-panel" aria-labelledby="repair-title" :aria-busy="loading || saving">
    <div class="panel-heading repair-heading">
      <h2 id="repair-title">针对性修复</h2>
      <button v-if="eligible && !createdJob" type="button" class="button secondary" :disabled="frozen" @click="preview"><AppIcon :name="plan ? 'refresh' : 'search'" />{{ loading ? '正在读取…' : plan ? '重新读取预览' : '查看可修复项' }}</button>
    </div>
    <p v-if="!eligible" class="field-help">检测未完整完成，暂不能修复。</p>
    <p v-if="loading" class="field-help" role="status">正在检查可修复项目…</p>
    <p v-if="error" class="notice error-notice" role="alert">{{ error }}</p>
    <template v-if="plan">
      <h3 ref="previewHeading" tabindex="-1" class="repair-preview-heading">{{ plan.available && candidates.length ? `可修复 ${candidates.length} 项` : '暂无可修复项目' }}</h3>
      <p v-if="plan.reason" class="field-help">{{ plan.reason }}</p>
      <form v-if="plan.available && candidates.length" @submit.prevent="apply">
        <ListPagination :page="page" :total="candidates.length" :disabled="frozen" label="可修复项分页" @change="setPage" />
        <fieldset class="repair-choices" :disabled="frozen">
          <legend class="visually-hidden">选择需要修复的格式问题</legend>
          <article v-for="candidate in displayed" :key="candidate.id" class="repair-candidate" :class="{ selected: selectedIds.includes(candidate.id) }">
            <label class="repair-choice">
              <input v-model="selectedIds" type="checkbox" :value="candidate.id" :aria-describedby="`repair-location-${candidate.id}`" />
              <span>{{ candidate.label?.replace(/（pt）/g, '（磅）').replace(/（mm）/g, '（毫米）') || '格式修复项' }}</span>
            </label>
            <p :id="`repair-location-${candidate.id}`" class="repair-location">{{ displayLocation(candidate.location) }}</p>
            <dl class="repair-comparison">
              <div><dt>实际格式</dt><dd>{{ displayRuleEvidence(candidate.actual, candidate.target || candidate.rule_id) }}</dd></div>
              <div><dt>修复为</dt><dd>{{ displayRuleEvidence(candidate.expected, candidate.target || candidate.rule_id) }}</dd></div>
            </dl>
          </article>
        </fieldset>
        <div class="repair-actions">
          <span class="field-help" role="status">已选 {{ selectedIds.length }} 项</span>
          <button class="button primary" type="submit" :disabled="!canSubmit || !!disabled">{{ saving ? '正在生成副本…' : '生成副本并复检' }}<AppIcon name="arrow-right" /></button>
        </div>
      </form>
      <details v-if="skipped.length" class="repair-skipped">
        <summary>{{ skipped.length }} 项需手动处理</summary>
        <ListPagination :page="skippedPage" :total="skipped.length" label="手动处理项分页" @change="setSkippedPage" />
        <ul>
          <li v-for="(item, index) in displayedSkipped" :key="`${skippedPage}-${index}`"><span v-if="item.location">{{ displayLocation(item.location) }}： </span>{{ item.reason }}</li>
        </ul>
      </details>
    </template>
    <p v-if="createdJob" role="status" class="notice neutral-notice">修复副本已生成，<a :href="`#job/${createdJob.id}`">查看复检任务</a>。</p>
  </section>
</template>

<style scoped>
.repair-panel {
  min-width: 0;
  margin-bottom: 20px;
  padding: var(--panel-padding, 22px);
}

.repair-heading {
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
}

.repair-heading h2 {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}

.repair-heading .button,
.repair-actions .button {
  max-width: 100%;
  white-space: normal;
  overflow-wrap: anywhere;
}

.repair-panel > .field-help:last-child {
  margin-bottom: 0;
}

.repair-preview-heading {
  margin-top: 18px;
  margin-bottom: 8px;
  overflow-wrap: anywhere;
}

.repair-choices {
  display: grid;
  gap: 12px;
  max-height: min(56vh, 560px);
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  min-width: 0;
  margin: 0;
  padding: 3px;
  border: 0;
}

.repair-candidate {
  min-width: 0;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow-wrap: anywhere;
}
.repair-candidate.selected { border-color: var(--brand); background: var(--brand-soft); }
.repair-panel form > .list-pagination { margin-bottom: 16px; }

.repair-choice {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-height: 32px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
}

.repair-choice input {
  flex: none;
  width: 18px;
  height: 18px;
  margin: 5px 0 0;
  accent-color: var(--brand);
}

.repair-choice span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.repair-choices:disabled .repair-choice {
  cursor: not-allowed;
}

.repair-location {
  margin: 0 0 12px 28px;
  color: var(--muted);
  font-size: 15px;
  overflow-wrap: anywhere;
}

.repair-comparison {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin: 0 0 0 28px;
}

.repair-comparison > div {
  min-width: 0;
  padding: 12px 14px;
  border-radius: 8px;
  background: var(--canvas);
  border: 1px solid var(--line);
}
.repair-comparison > div:last-child { background: var(--surface); }

.repair-comparison dt {
  color: var(--muted);
  font-size: 13px;
}

.repair-comparison dd {
  margin: 2px 0 0;
  font-size: 15px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.repair-actions,
.repair-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 16px;
}

.repair-actions {
  padding-top: 20px;
  border-top: 1px solid var(--line);
}

.repair-actions .field-help,
.repair-pagination .field-help {
  margin: 0;
}

.repair-actions .button {
  font-size: 15px;
}

.repair-skipped {
  margin-top: 18px;
  overflow-wrap: anywhere;
}

.repair-skipped summary {
  min-height: 44px;
  padding-block: 10px;
  color: var(--brand);
  font-size: 15px;
  cursor: pointer;
}

.repair-skipped ul {
  margin: 8px 0 0;
  padding-left: 22px;
}

.repair-skipped li {
  padding-block: 4px;
  font-size: 15px;
}

.repair-skipped .text-button,
.repair-pagination .text-button {
  min-height: 44px;
}

.repair-panel .notice {
  overflow-wrap: anywhere;
}

@media (max-width: 767px) {
  .repair-candidate { padding: 14px; }
  .repair-panel {
    padding: var(--panel-padding, 18px);
  }

  .repair-heading,
  .repair-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .repair-comparison {
    grid-template-columns: 1fr;
  }

  .repair-location,
  .repair-comparison {
    margin-left: 0;
  }
}

@container workspace (max-width: 600px) {
  .repair-panel {
    padding: var(--panel-padding, 18px);
  }

  .repair-heading,
  .repair-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .repair-comparison {
    grid-template-columns: 1fr;
  }

  .repair-location,
  .repair-comparison {
    margin-left: 0;
  }
}
</style>
