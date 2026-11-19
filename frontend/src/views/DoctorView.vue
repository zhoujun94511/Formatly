<script setup lang="ts">
import { computed } from 'vue'
import type { DoctorReport } from '../types'
import AppIcon from '../components/AppIcon.vue'
import StatusBadge from '../components/StatusBadge.vue'
import ListPagination from '../components/ListPagination.vue'
import ExternalEngineSetupPanel from '../components/ExternalEngineSetupPanel.vue'
import { usePagedItems } from '../composables/usePagedItems'

const props = defineProps<{ report: DoctorReport | null; loading?: boolean }>()
const emit = defineEmits<{ refresh: [] }>()
const checks = computed(() => (props.report?.checks || []).filter(check => !props.report?.external_engine || check.id !== props.report.external_engine.plugin_id))
const { page, displayed, setPage } = usePagedItems(checks, 10, false)
const isReady = (status?: string) => ['ok', 'ready', 'available', 'success', 'passed'].includes(status || '')
const environmentStatus = computed(() => checks.value.length ? checks.value.every(check => isReady(check.status)) ? 'ready' : 'degraded' : undefined)
</script>

<template>
  <div class="page environment-page">
    <div class="page-heading">
      <div><h1>运行环境</h1></div>
      <button class="button secondary" type="button" :disabled="loading" @click="emit('refresh')"><AppIcon name="refresh" />{{ loading ? '正在检查…' : '重新检查' }}</button>
    </div>
    <section class="panel environment-panel" aria-label="运行环境检查结果" :aria-busy="!!loading">
      <div class="environment-overview" role="status" aria-live="polite">
        <strong>{{ loading ? '正在检查运行环境…' : report ? '内置检测环境' : '尚未检查运行环境' }}</strong>
        <StatusBadge v-if="!loading && environmentStatus" :status="environmentStatus" />
      </div>
      <ul class="environment-checks">
        <li v-for="(check, index) in displayed" :key="check.id || `${check.name}-${(page - 1) * 10 + index}`" class="environment-check">
          <span class="check-icon" :class="{ 'check-ready': isReady(check.status) }"><AppIcon :name="isReady(check.status) ? 'check' : 'alert'" /></span>
          <div class="check-content"><h2>{{ check.name || check.id }}</h2><p v-if="check.message || check.detail">{{ check.message || check.detail }}</p></div>
          <StatusBadge :status="check.status" />
        </li>
      </ul>
      <p v-if="report && !loading && !checks.length" class="empty-state">暂无检查结果</p>
      <ListPagination :page="page" :total="checks.length" :disabled="loading" label="运行环境分页" @change="setPage" />
    </section>
    <details v-if="report?.external_engine" class="optional-engine-section">
      <summary>外部专项引擎（可选）</summary>
      <ExternalEngineSetupPanel :engine="report.external_engine" :loading="loading" @refresh="emit('refresh')" />
    </details>
  </div>
</template>

<style scoped>
.environment-panel { padding: 0 var(--panel-padding) var(--panel-padding); }
.optional-engine-section { margin-top: 24px; }
.optional-engine-section > summary { cursor: pointer; padding-block: 12px; font-weight: 600; }
.optional-engine-section > summary:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
.environment-overview { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; padding-block: 20px; border-bottom: 1px solid var(--line); }
.environment-overview strong { font-size: 16px; font-weight: 600; }
.environment-checks { list-style: none; margin: 0; padding: 0; }
.environment-check { display: grid; grid-template-columns: 36px minmax(0, 1fr) auto; gap: 14px; align-items: start; padding-block: 20px; border-bottom: 1px solid var(--line); }
.environment-check:last-child { border-bottom: 0; }
.check-icon { display: grid; place-items: center; width: 36px; height: 36px; color: var(--warning); background: var(--warning-bg); border-radius: 9px; }
.check-ready { color: var(--success); background: var(--success-bg); }
.check-content { min-width: 0; }
.check-content h2 { font-size: 16px; font-weight: 600; line-height: 1.5; }
.check-content p { margin: 4px 0 0; color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }
.environment-check > .status-badge { margin-top: 4px; }
@container workspace (max-width: 560px) { .environment-check { grid-template-columns: 32px minmax(0, 1fr); gap: 8px 12px; } .check-icon { width: 32px; height: 32px; } .environment-check > .status-badge { grid-column: 2; justify-self: start; margin-top: 0; } }
@media (max-width: 480px) { .environment-check { grid-template-columns: 32px minmax(0, 1fr); gap: 8px 12px; } .check-icon { width: 32px; height: 32px; } .environment-check > .status-badge { grid-column: 2; justify-self: start; margin-top: 0; } }
</style>

