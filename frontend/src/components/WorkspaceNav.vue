<script setup lang="ts">
import { computed } from 'vue'
import type { Page } from '../types'

const props = defineProps<{ page: Page }>()
const groups: { pages: Page[]; label: string; links: [Page, string][] }[] = [
  { pages: ['schools', 'profiles'], label: '学校要求', links: [['schools', '模板与格式说明'], ['profiles', '已保存方案']] },
  { pages: ['history', 'collections'], label: '检测记录', links: [['history', '全部记录'], ['collections', '材料分组核验']] },
  { pages: ['doctor', 'plugins'], label: '设置', links: [['doctor', '运行环境'], ['plugins', '检测能力']] },
]
const group = computed(() => groups.find(item => item.pages.includes(props.page)))
</script>

<template>
  <nav v-if="group" class="workspace-nav" :aria-label="`${group.label}分类`">
    <a v-for="[id, label] in group.links" :key="id" :href="`#${id}`" :aria-current="page === id ? 'page' : undefined">{{ label }}</a>
  </nav>
</template>

<style scoped>
.workspace-nav { display: flex; flex-wrap: wrap; gap: 24px; margin-bottom: 28px; border-bottom: 1px solid var(--line); }
a { display: inline-flex; align-items: center; justify-content: center; min-height: 44px; padding: 8px 2px 12px; border-bottom: 2px solid transparent; margin-bottom: -1px; text-decoration: none; color: var(--muted); font-size: 15px; font-weight: 600; }
a:hover { color: var(--ink); }
a[aria-current="page"] { border-bottom-color: var(--brand); color: var(--brand); }
@media (max-width: 400px) { a { flex: 1 1 auto; padding-inline: 10px; } }
</style>
