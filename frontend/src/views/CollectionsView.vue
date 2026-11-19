<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { DocumentKind } from '../types'
import { useCollectionWorkspace } from '../composables/useCollectionWorkspace'
import { documentKinds, kindLabel } from '../utils/materials'
import RuleCheckList from '../components/RuleCheckList.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { formatDateTime } from '../utils/date'
import WorkspaceWarnings from '../components/WorkspaceWarnings.vue'
import ListPagination from '../components/ListPagination.vue'
import { usePagedItems } from '../composables/usePagedItems'
import AppIcon from '../components/AppIcon.vue'

const props = defineProps<{ selectedId?: string; refreshToken?: number }>()
const emit = defineEmits<{ select: [string]; open: [string]; add: [string] }>()
const workspace = useCollectionWorkspace()
const { items, selected, collectionWarnings, loading, saving, error } = workspace
const collectionJobs = computed(() => selected.value?.items || [])
const { page, displayed, setPage } = usePagedItems(collectionJobs, 10, false)
const name = ref(''), kinds = ref<DocumentKind[]>(['thesis', 'intern', 'certificate'])
watch(() => props.selectedId, id => { setPage(1); void workspace.select(id || '') }, { immediate: true })
watch(() => props.refreshToken, () => { void workspace.refresh(); if (props.selectedId) void workspace.select(props.selectedId) })
async function create() {
  if (!name.value.trim() || !kinds.value.length) return
  const value = await workspace.create(name.value.trim(), kinds.value)
  if (value) { name.value = ''; emit('select', value.id) }
}
onMounted(async () => { await workspace.refresh(); if (!props.selectedId && items.value[0]) emit('select', items.value[0].id) })
</script>
<template>
  <div class="page materials-page collections-page">
    <div class="page-heading"><div><h1>材料分组核验</h1><p>将论文、实习报告和证明归为一组，核对关键信息是否一致。</p></div></div>
    <p v-if="error" class="notice error-notice" role="alert">{{ error }} <button class="text-button" type="button" :disabled="loading" @click="selectedId ? workspace.select(selectedId) : workspace.refresh()">重新读取</button></p>
    <WorkspaceWarnings :warnings="collectionWarnings" label="材料集合" />
    <section class="panel collection-picker">
      <div class="form-group"><label for="collection-picker">已保存的材料分组</label><select id="collection-picker" :value="selectedId || ''" :disabled="saving || loading" @change="emit('select', ($event.target as HTMLSelectElement).value)"><option value="">请选择分组</option><option v-for="item in items" :key="item.id" :value="item.id">{{ item.name }}</option></select></div>
    </section>
    <details class="panel collection-create" :open="!items.length && !selected">
      <summary><span class="collection-symbol"><AppIcon name="plus" /></span><span><strong>新建材料分组</strong><small>为同一次提交的材料建立核验分组</small></span><AppIcon name="chevron-right" /></summary>
      <form @submit.prevent="create"><fieldset class="dialog-fields" :disabled="saving"><div class="form-group"><label for="collection-name">分组名称</label><input id="collection-name" v-model="name" maxlength="120" required placeholder="例如：本次毕业材料" /></div><fieldset class="plugin-fieldset"><legend>必需材料</legend><label v-for="kind in documentKinds" :key="kind.value"><input v-model="kinds" type="checkbox" :value="kind.value" /> {{ kind.label }}</label></fieldset><div class="collection-create-actions"><button class="button primary" type="submit" :disabled="saving || !name.trim() || !kinds.length">{{ saving ? '正在创建…' : '创建分组' }}<AppIcon name="arrow-right" /></button></div></fieldset></form>
    </details>
    <p v-if="loading && !selected" class="empty-state" role="status">正在读取材料核验…</p>
    <template v-if="selected">
      <section class="panel materials-panel collection-documents">
        <div class="panel-heading"><div><h2>{{ selected.name }}</h2><p class="field-help">必需材料：{{ (selected.required_kinds || []).map(kindLabel).join('、') || '未指定' }}</p></div><StatusBadge :status="selected.status" :label="selected.status === 'passed' ? '已提取字段一致' : selected.status === 'needs_changes' ? '字段存在冲突' : '字段待复核'" /></div>
        <p class="field-help">使用各类型最新检测结果。<span v-if="selected.excluded_revision_ids?.length">已排除 {{ selected.excluded_revision_ids.length }} 个较早版本。</span></p>
        <div class="collection-actions"><button class="button secondary" type="button" :disabled="loading" @click="workspace.select(selected.id)"><AppIcon name="refresh" />刷新核验</button><button class="button primary" type="button" :disabled="loading || saving" @click="emit('add', selected.id)"><AppIcon name="plus" />添加检测文档</button></div>
        <ListPagination :page="page" :total="collectionJobs.length" label="材料记录分页" @change="setPage" /><div class="job-list"><button v-for="job in displayed" :key="job.id" type="button" class="job-row" @click="emit('open', job.id)"><span class="job-file-icon" aria-hidden="true"><AppIcon name="file" /></span><span class="job-row-main"><strong>{{ job.filename }}</strong><small>{{ kindLabel(job.kind) }} · {{ formatDateTime(job.created_at) }}</small><small v-if="selected.excluded_revision_ids?.includes(job.id)">较早版本，不参与本次比较</small></span><StatusBadge :status="job.result?.status || job.status" /><AppIcon name="chevron-right" /></button><p v-if="!selected.items?.length" class="empty-state">暂无文档，点击“添加检测文档”开始。</p></div>
      </section>
      <section class="panel materials-panel"><div class="panel-heading"><h2>核验结果</h2></div><div v-if="selected.summary" class="coverage-summary"><span>通过 {{ selected.summary.passed || 0 }}</span><span>不符合 {{ selected.summary.failed || 0 }}</span><span>待复核 {{ selected.summary.manual || 0 }}</span><span>未执行 {{ selected.summary.not_checked || 0 }}</span></div><RuleCheckList :checks="selected.checks || []" :identity="selected.id" /></section>
    </template>
  </div>
</template>

<style scoped>
.collection-picker { padding: 20px 24px; margin-bottom: 16px; }
.collection-picker .form-group { margin: 0; }
.collection-create { margin-bottom: 24px; padding: 0; overflow: hidden; }
.collection-create > summary { display: flex; align-items: center; gap: 12px; list-style: none; padding: 20px 24px; cursor: pointer; }
.collection-create > summary::-webkit-details-marker { display: none; }
.collection-create > summary:hover { background: var(--surface-hover); }
.collection-create > summary > span:not(.collection-symbol) { flex: 1; min-width: 0; }
.collection-create strong, .collection-create small { display: block; overflow-wrap: anywhere; }
.collection-create strong { font-size: 16px; font-weight: 600; }
.collection-create small { font-size: 14px; color: var(--muted); margin-top: 3px; }
.collection-symbol { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 8px; background: var(--brand-soft); color: var(--brand); flex: none; }
.collection-symbol :deep(svg) { width: 18px; height: 18px; }
.collection-create > summary > :deep(svg) { width: 18px; height: 18px; color: var(--muted); flex: none; }
.collection-create[open] > summary > :deep(svg) { transform: rotate(90deg); }
.collection-create > form { padding: 24px; border-top: 1px solid var(--line); }
.collection-create .plugin-fieldset { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 0; padding: 16px; }
.collection-create .plugin-fieldset label { display: flex; align-items: center; gap: 8px; font-size: 15px; }
.collection-create-actions { display: flex; justify-content: flex-end; margin-top: 20px; }
.materials-panel { padding: 24px; }
.collection-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 10px; margin-block: 20px; }
.collection-documents .job-list { border-top: 1px solid var(--line); }
.job-row > :deep(svg) { width: 17px; height: 17px; flex: none; color: var(--subtle); }
@container workspace (max-width: 640px) { .collection-picker, .materials-panel, .collection-create > form { padding: 20px; } .collection-create > summary { padding: 18px 20px; } .collection-create .plugin-fieldset { grid-template-columns: 1fr; } .collection-actions .button { flex: 1 1 auto; } .collection-create-actions .button { width: 100%; } }
@media (max-width: 480px) { .collection-picker, .materials-panel, .collection-create > form { padding: 20px; } .collection-create > summary { padding: 18px 20px; } .collection-create .plugin-fieldset { grid-template-columns: 1fr; } }
</style>
