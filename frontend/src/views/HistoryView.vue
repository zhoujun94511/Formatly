<script setup lang="ts">
import { toRef, watch } from 'vue'
import StatusBadge from '../components/StatusBadge.vue'
import AppIcon from '../components/AppIcon.vue'
import { useJobHistory } from '../composables/useJobHistory'
import { formatDateTime } from '../utils/date'
import { kindLabel } from '../utils/materials'
import ListPagination from '../components/ListPagination.vue'
import { usePagedItems } from '../composables/usePagedItems'
const props = defineProps<{ refreshToken?: number }>()
const emit = defineEmits<{ open: [string] }>()
const { query, status, items, total, loading, error, hasMore, reload, loadMore } = useJobHistory(toRef(props, 'refreshToken'))
const { page, displayed, setPage } = usePagedItems(items, 10, false)
watch([query, status], () => setPage(1), { flush: 'sync' })
async function readMore() {
  const previousCount = items.value.length, wantedPage = Math.floor(previousCount / 10) + 1
  const previousQuery = query.value, previousStatus = status.value
  await loadMore()
  if (query.value === previousQuery && status.value === previousStatus && items.value.length > previousCount) setPage(wantedPage)
}
</script>
<template>
  <div class="page history-page">
    <div class="page-heading"><div><h1>检测记录</h1><p>查看检测结果，继续修改与复检。</p></div><a class="button primary" href="#new"><AppIcon name="plus" />新建检测</a></div>
    <section class="panel history-panel" :aria-busy="loading" aria-label="检测记录列表">
      <div class="table-toolbar history-toolbar">
        <label class="search-field"><AppIcon name="search" /><input v-model="query" type="search" maxlength="200" placeholder="搜索文档名称" aria-label="搜索检测记录"/></label>
        <label class="inline-label"><span>任务状态</span><select v-model="status"><option value="">全部状态</option><option value="completed">检测完成</option><option value="running">正在检测</option><option value="queued">等待执行</option><option value="failed">执行失败</option><option value="interrupted">已中断</option><option value="cancelled">已取消</option></select></label>
      </div>
      <div v-if="error" class="notice error-notice" role="alert">{{ error }} <button class="text-button" type="button" :disabled="loading" @click="reload">重试</button></div>
      <div class="history-columns" aria-hidden="true"><span>检测文档</span><span>检测状态</span><span>创建时间</span><span></span></div>
      <div class="job-list">
        <button v-for="job in displayed" :key="job.id" type="button" class="job-row history-row" @click="emit('open', job.id)">
          <span class="history-document"><span class="job-file-icon" aria-hidden="true"><AppIcon name="file" /></span><span class="job-row-main"><strong>{{ job.filename || '未命名文档' }}</strong><small>{{ kindLabel(job.kind) }}<span v-if="job.result?.counts" class="history-counts">错误 {{ job.result.counts.error || 0 }}<span aria-hidden="true"> / </span>风险 {{ job.result.counts.warning || 0 }}<span aria-hidden="true"> / </span>复核 {{ job.result.counts.manual || 0 }}</span></small><small class="history-inline-date"><time v-if="job.created_at" :datetime="job.created_at">{{ formatDateTime(job.created_at) }}</time><span v-else>时间未记录</span></small></span></span>
          <span class="job-status-stack"><StatusBadge :status="job.status"/><StatusBadge v-if="job.result?.status" :status="job.result.status"/></span>
          <span class="history-date"><time v-if="job.created_at" :datetime="job.created_at">{{ formatDateTime(job.created_at) }}</time><span v-else>时间未记录</span></span>
          <AppIcon name="chevron-right" class="history-open" />
        </button>
        <p v-if="loading && !items.length" class="empty-state" role="status">正在读取检测记录…</p>
        <div v-else-if="!items.length && !error" class="empty-state history-empty"><AppIcon name="history" /><strong>{{ query || status ? '没有匹配的检测记录' : '还没有检测记录' }}</strong><button v-if="query || status" class="text-button" type="button" @click="query = ''; status = ''">清除筛选</button><a v-else class="button secondary" href="#new">开始第一次检测</a></div>
      </div>
      <div class="history-footer"><ListPagination :page="page" :total="items.length" :disabled="loading" label="检测记录分页" @change="setPage" /><div class="history-load-more"><span class="muted" role="status">已读取 {{ items.length }} / {{ total }} 条</span><button v-if="hasMore" class="button secondary" type="button" :disabled="loading" @click="readMore">{{ loading ? '正在读取…' : '读取后续记录' }}</button></div></div>
    </section>
  </div>
</template>

<style scoped>
.history-panel { overflow: hidden; }
.history-toolbar { padding: 20px 24px; margin: 0; }
.history-toolbar .search-field { --search-basis: 260px; max-width: 420px; }
.history-columns, .history-row { display: grid; grid-template-columns: minmax(0, 1fr) 170px 155px 20px; column-gap: 20px; align-items: center; }
.history-columns { padding: 12px 24px; background: var(--canvas); color: var(--muted); font-size: 13px; border-block: 1px solid var(--line); }
.history-row { padding: 18px 24px; min-height: 96px; }
.history-document { display: flex; align-items: center; gap: 14px; min-width: 0; }
.history-document .job-file-icon { display: grid; width: 40px; height: 44px; border-radius: 8px; background: var(--canvas); color: var(--muted); }
.history-document .job-row-main { min-width: 0; }
.history-document .job-row-main strong { font-weight: 600; }
.history-document small { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 4px; }
.history-document .history-inline-date { display: none; font-variant-numeric: tabular-nums; }
.history-counts { color: var(--muted); }
.history-row .job-status-stack { align-items: flex-start; justify-content: flex-start; max-width: none; width: 100%; }
.history-date { font-size: 13px; color: var(--muted); text-align: left; font-variant-numeric: tabular-nums; }
.history-open { color: var(--muted); }
.history-row:hover .history-open { color: var(--brand); }
.history-footer { padding: 0 24px 20px; border-top: 1px solid var(--line); }
.history-load-more { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; padding-top: 16px; font-size: 14px; }
.history-empty { display: flex; flex-direction: column; align-items: center; gap: 14px; padding-block: 56px; }
.history-empty > svg { width: 32px; height: 32px; color: var(--muted); }
.history-empty strong { font-size: 16px; font-weight: 500; }
@container workspace (max-width: 1000px) { .history-columns, .history-row { grid-template-columns: minmax(0, 1fr) 140px 20px; } .history-columns > span:nth-child(3), .history-date { display: none; } .history-document .history-inline-date { display: flex; } }
@container workspace (max-width: 620px) { .history-columns { display: none; } .history-row { grid-template-columns: minmax(0, 1fr) 20px; gap: 10px 12px; padding: 18px; } .history-row .job-status-stack { grid-row: 2; flex-direction: row; margin-left: 54px; justify-content: flex-start; flex-wrap: wrap; } .history-open { grid-column: 2; grid-row: 1; } .history-toolbar { padding: 18px; } .history-toolbar .search-field { max-width: none; } .history-footer { padding-inline: 18px; } }
@media (max-width: 640px) { .history-columns { display: none; } .history-row { grid-template-columns: minmax(0, 1fr) 20px; gap: 10px 12px; padding: 18px; } .history-date { display: none; } .history-document .history-inline-date { display: flex; } .history-row .job-status-stack { grid-row: 2; flex-direction: row; margin-left: 54px; justify-content: flex-start; flex-wrap: wrap; } .history-open { grid-column: 2; grid-row: 1; } .history-toolbar { padding: 18px; } .history-toolbar .search-field { max-width: none; } .history-footer { padding-inline: 18px; } }
</style>
