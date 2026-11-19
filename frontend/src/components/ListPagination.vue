<script setup lang="ts">
import AppIcon from './AppIcon.vue'
withDefaults(defineProps<{ page: number; total: number; pageSize?: number; disabled?: boolean; label: string }>(), { pageSize: 10 })
const emit = defineEmits<{ change: [number] }>()
</script>
<template>
  <nav v-if="total > pageSize" class="list-pagination" :aria-label="label">
    <span role="status">第 {{ page }} / {{ Math.ceil(total / pageSize) }} 页 · 共 {{ total }} 项</span>
    <div class="pagination-controls"><button class="button secondary" type="button" :disabled="disabled || page <= 1" @click="emit('change', page - 1)"><AppIcon name="chevron-right" class="previous-icon" />上一页</button>
    <button class="button secondary" type="button" :disabled="disabled || page >= Math.ceil(total / pageSize)" @click="emit('change', page + 1)">下一页<AppIcon name="chevron-right" /></button></div>
  </nav>
</template>
<style scoped>
.list-pagination { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin-block: 20px 0; padding-top: 16px; border-top: 1px solid var(--line); }
.list-pagination span { color: var(--muted); font-size: 14px; }
.pagination-controls { display: flex; flex-wrap: wrap; gap: 8px; }
.pagination-controls .button { gap: 6px; padding-inline: 12px; font-size: 14px; }
.pagination-controls svg { width: 16px; height: 16px; }
.previous-icon { transform: rotate(180deg); }
@media (max-width: 480px) { .pagination-controls { width: 100%; justify-content: space-between; } }
</style>
