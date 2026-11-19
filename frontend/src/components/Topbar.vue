<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import ThemeToggle from './ThemeToggle.vue'
defineProps<{ title: string; loading?: boolean }>()
const emit = defineEmits<{ refresh: [] }>()
</script>
<template>
  <header class="topbar">
    <div class="breadcrumb"><span>工作台</span><AppIcon name="chevron-right" :size="14" /><strong>{{ title }}</strong></div>
    <div class="topbar-actions"><ThemeToggle /><button class="button topbar-refresh" type="button" aria-label="刷新数据" :disabled="loading" @click="emit('refresh')"><AppIcon name="refresh" :size="17" :class="{ refreshing: loading }" /><span>{{ loading ? '刷新中' : '刷新' }}</span></button></div>
  </header>
</template>
<style scoped>
.breadcrumb { display: flex; align-items: center; gap: 10px; }
.breadcrumb > span { color: var(--muted); }
.topbar-actions { display: flex; align-items: center; flex: none; gap: 8px; }
.topbar-refresh { min-height: 44px; padding: 6px 10px; color: var(--muted); background: transparent; font-size: 14px; font-weight: 500; }
.topbar-refresh:hover:not(:disabled) { color: var(--ink); background: var(--canvas); }
.refreshing { animation: spin 1s linear infinite; }
@media (max-width: 400px) { .breadcrumb { gap: 6px; } .breadcrumb > span, .breadcrumb > .app-icon { display: none; } }
</style>

