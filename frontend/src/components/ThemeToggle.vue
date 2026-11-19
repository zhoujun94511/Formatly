<script setup lang="ts">
import { useTheme } from '../composables/useTheme'
import AppIcon from './AppIcon.vue'

const { isDark, toggle } = useTheme()
</script>

<template>
  <button class="theme-toggle" type="button" role="switch" aria-label="深色模式" :aria-checked="isDark"
    :title="isDark ? '切换为浅色模式' : '切换为深色模式'" @click="toggle">
    <AppIcon :name="isDark ? 'moon' : 'sun'" :size="18" />
    <span>{{ isDark ? '深色' : '浅色' }}</span>
  </button>
</template>

<style scoped>
.theme-toggle { display: inline-flex; align-items: center; justify-content: center; flex: none; gap: 7px; min-width: 44px; min-height: 44px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--muted); font-size: 14px; line-height: 1.4; }
.theme-toggle:hover { border-color: var(--line-strong); color: var(--ink); background: var(--surface-hover); }
@media (max-width: 480px) { .theme-toggle { padding: 8px; } .theme-toggle > span { display: none; } }
</style>
