<script setup lang="ts">
import { computed } from 'vue'
import type { Plugin } from '../types'
import AppIcon from '../components/AppIcon.vue'
import StatusBadge from '../components/StatusBadge.vue'
import ListPagination from '../components/ListPagination.vue'
import { usePagedItems } from '../composables/usePagedItems'
import { formatLabel } from '../utils/documents'
import { engineLabel } from '../utils/report'

const props = defineProps<{ plugins: Plugin[] }>()
const plugins = computed(() => props.plugins)
const availableCount = computed(() => plugins.value.filter(plugin => plugin.available).length)
const { page, displayed, setPage } = usePagedItems(plugins, 10, false)
</script>
<template>
  <div class="page capabilities-page">
    <div class="page-heading"><div><h1>检测能力</h1></div></div>
    <section class="panel capabilities-panel" aria-label="检测能力列表">
      <div class="capabilities-overview"><strong>已配置的检测能力</strong><span>{{ availableCount }} / {{ plugins.length }} 项可用</span></div>
      <ul class="capabilities-list">
        <li v-for="plugin in displayed" :key="plugin.id" class="capability-row">
          <span class="capability-icon"><AppIcon name="layers" /></span>
          <div class="capability-content">
            <div class="capability-heading"><h2>{{ engineLabel(plugin.id, plugin.name) }}</h2><StatusBadge :status="plugin.available ? 'available' : 'unavailable'" /></div>
            <p v-if="plugin.formats?.length" class="capability-formats">支持格式：{{ plugin.formats.map(formatLabel).join(' / ') }}</p>
            <p v-if="!plugin.available && plugin.reason" class="capability-reason">{{ plugin.reason }}</p>
            <a v-if="plugin.id === 'legacy-school'" class="capability-setup" href="#doctor">接入与检查<AppIcon name="arrow-right" /></a>
            <details class="capability-details"><summary>查看详情</summary><p v-if="plugin.description">{{ plugin.description }}</p><p v-if="plugin.available && plugin.reason && plugin.reason !== plugin.description">{{ plugin.reason }}</p><p class="capability-id">组件标识：<code>{{ plugin.id }}</code></p></details>
          </div>
        </li>
      </ul>
      <p v-if="!plugins.length" class="empty-state">暂无已配置的检测能力</p>
      <ListPagination :page="page" :total="plugins.length" label="检测能力分页" @change="setPage" />
    </section>
  </div>
</template>

<style scoped>
.capabilities-panel { padding: 0 var(--panel-padding) var(--panel-padding); }
.capabilities-overview { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px; padding-block: 20px; border-bottom: 1px solid var(--line); }
.capabilities-overview strong { font-size: 16px; font-weight: 600; }
.capabilities-overview > span { color: var(--muted); font-size: 14px; }
.capabilities-list { list-style: none; margin: 0; padding: 0; }
.capability-row { display: grid; grid-template-columns: 40px minmax(0, 1fr); gap: 16px; padding-block: 24px; border-bottom: 1px solid var(--line); }
.capability-row:last-child { border-bottom: 0; }
.capability-icon { display: grid; place-items: center; width: 40px; height: 40px; background: var(--brand-soft); color: var(--brand); border-radius: 10px; }
.capability-content { min-width: 0; }
.capability-heading { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px 16px; }
.capability-heading h2 { font-size: 17px; font-weight: 600; line-height: 1.5; overflow-wrap: anywhere; }
.capability-formats, .capability-reason { margin: 8px 0 0; font-size: 14px; color: var(--muted); }
.capability-reason { color: var(--warning); overflow-wrap: anywhere; }
.capability-setup { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; font-size: 14px; }
.capability-details { margin-top: 4px; color: var(--muted); font-size: 14px; }
.capability-details summary { cursor: pointer; min-height: 44px; padding-block: 10px; width: fit-content; }
.capability-details p { margin: 4px 0 12px; overflow-wrap: anywhere; }
.capability-id code { font-size: 13px; }
@container workspace (max-width: 560px) { .capability-row { grid-template-columns: minmax(0, 1fr); gap: 10px; } .capability-icon { display: none; } }
@media (max-width: 480px) { .capability-row { grid-template-columns: minmax(0, 1fr); gap: 10px; } .capability-icon { display: none; } }
</style>

