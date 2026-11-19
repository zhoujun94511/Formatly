<script setup lang="ts">
import { computed } from 'vue'
import type { Artifact } from '../types'
import ArtifactLink from './ArtifactLink.vue'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ items: Artifact[]; loading?: boolean }>()
const primaryOrder = ['report.html', 'repaired.docx', 'report.md', 'report.json']
const rank = (item: Artifact) => primaryOrder.indexOf(item.path || item.name || '')
const primary = computed(() => props.items.filter(item => rank(item) >= 0).sort((left, right) => rank(left) - rank(right)))
const secondary = computed(() => props.items.filter(item => rank(item) < 0))
const visible = computed(() => primary.value.length ? primary.value : props.items)
</script>

<template>
  <div class="artifact-list">
    <p v-if="loading" class="empty-state" role="status" aria-live="polite">正在读取附件…</p>
    <p v-else-if="!items.length" class="empty-state">暂无可下载的附件</p>
    <template v-else>
      <p v-if="items.some(item => item.integrity === 'unverified')" class="notice warm-notice" role="status">部分历史附件的完整性尚未验证。</p>
      <div :class="primary.length ? 'artifact-primary-list' : 'artifact-secondary-list'" :tabindex="primary.length ? undefined : 0" :role="primary.length ? undefined : 'region'" :aria-label="primary.length ? undefined : '任务附件'"><ArtifactLink v-for="item in visible" :key="item.url || item.path" :item="item" /></div>
      <details v-if="primary.length && secondary.length" class="artifact-more">
        <summary>更多附件（{{ secondary.length }}）<AppIcon name="chevron-right" /></summary>
        <div class="artifact-secondary-list" tabindex="0" role="region" aria-label="更多附件"><ArtifactLink v-for="item in secondary" :key="item.url || item.path" :item="item" /></div>
      </details>
    </template>
  </div>
</template>

<style scoped>
.artifact-primary-list, .artifact-secondary-list { display: grid; gap: 8px; min-width: 0; }
.artifact-secondary-list { max-height: 320px; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; padding: 3px; }
.artifact-more { border-top: 1px solid var(--line); margin-top: 8px; padding-top: 4px; min-width: 0; }
.artifact-more > summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 44px; padding: 10px 2px; cursor: pointer; color: var(--muted); font-size: 14px; list-style: none; }
.artifact-more > summary::-webkit-details-marker { display: none; }
.artifact-more[open] > summary svg { transform: rotate(90deg); }
.artifact-more > summary:hover { color: var(--brand); }
</style>

