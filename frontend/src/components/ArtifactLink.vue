<script setup lang="ts">
import type { Artifact } from '../types'
import AppIcon from './AppIcon.vue'

defineProps<{ item: Artifact }>()

function label(item: Artifact) {
  const path = item.path || item.name
  if (path === 'report.html') return '下载检测报告'
  if (path === 'repaired.docx') return '下载修复文档'
  if (path === 'repair.json') return '修改记录（JSON）'
  if (path === 'export-integrity.json') return '附件完整性记录（JSON）'
  const names: Record<string, string> = {
    'report.json': '检测结果数据（JSON）', 'report.md': '文字报告',
    'artifacts-manifest.json': '附件校验清单', 'document-extraction.json': '文档提取记录',
    'document-fields/fields.json': '材料字段记录（JSON）', 'fields.json': '材料字段记录（JSON）',
    'input.docx': '原稿文档', 'input.pdf': '原稿文档', 'input.txt': '原稿文档',
    'input.md': '原稿文档', 'input.json': '原稿文档', 'paired.pdf': '配对文档',
    'profile.json': '本次检测方案', 'request.json': '任务信息', 'runtime.json': '运行记录',
  }
  if (path && names[path]) return names[path]
  return item.name || item.path
}

function size(value?: number) {
  if (!value) return '大小未记录'
  return value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1048576).toFixed(1)} MB`
}
</script>

<template>
  <a class="artifact-link" :href="item.url" :download="item.name || item.path" :aria-label="label(item)">
    <span class="artifact-icon" aria-hidden="true"><AppIcon name="file" /></span>
    <span class="artifact-description"><strong>{{ label(item) }}</strong><small>{{ size(item.size) }}</small></span>
    <AppIcon name="download" class="artifact-download" />
  </a>
</template>

<style scoped>
.artifact-link { grid-template-columns: 34px minmax(0, 1fr) 20px; gap: 12px; padding: 12px 14px; background: var(--surface); border-color: var(--line); border-radius: 8px; }
.artifact-link:hover { border-color: var(--brand); background: var(--canvas); }
.artifact-icon { display: grid; place-items: center; width: 34px; height: 38px; border: 1px solid var(--line); border-radius: 7px; background: var(--canvas); color: var(--muted); }
.artifact-icon svg { width: 18px; height: 18px; }
.artifact-description strong { font-size: 15px; font-weight: 600; }
.artifact-description small { font-size: 13px; margin-top: 2px; color: var(--muted); }
.artifact-download { color: var(--muted); }
.artifact-link:hover .artifact-download { color: var(--brand); }
</style>
