<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { Page } from '../types'
import AppIcon from './AppIcon.vue'
import { displayCount } from '../utils/numbers'

const props = defineProps<{ page: Page; historyCount: number }>()
const emit = defineEmits<{ navigate: [Page] }>()
const mobileOpen = ref(false)
const menuButton = ref<HTMLButtonElement>()
const items: [Page, string, string][] = [
  ['new', 'plus', '新建检测'],
  ['schools', 'school', '学校要求'],
  ['history', 'history', '检测记录'],
  ['doctor', 'settings', '设置'],
]

watch(() => props.page, () => { mobileOpen.value = false })

function isActive(page: Page) {
  return props.page === page
    || (props.page === 'batch' && page === 'new')
    || (['result', 'collections'].includes(props.page) && page === 'history')
    || (props.page === 'profiles' && page === 'schools')
    || (props.page === 'plugins' && page === 'doctor')
}

function navigate(page: Page) {
  const focusMenu = mobileOpen.value && props.page === page
  mobileOpen.value = false
  emit('navigate', page)
  if (focusMenu) void nextTick(() => menuButton.value?.focus())
}

function closeOnEscape(event: KeyboardEvent) {
  if (!mobileOpen.value) return
  event.preventDefault()
  event.stopPropagation()
  mobileOpen.value = false
  void nextTick(() => menuButton.value?.focus())
}
</script>

<template>
  <aside
    class="sidebar"
    :class="{ 'mobile-open': mobileOpen }"
    aria-label="Formatly 导航"
    @keydown.esc="closeOnEscape"
  >
    <div class="sidebar-header">
      <button class="brand" type="button" @click="navigate('new')">
        <span class="brand-mark"><img src="/assets/formatly-mark.png" alt="" /></span>
        <span class="brand-wordmark">Formatly</span>
      </button>
      <button
        ref="menuButton"
        class="icon-button mobile-nav-toggle"
        type="button"
        aria-controls="main-navigation"
        :aria-expanded="mobileOpen"
        :aria-label="mobileOpen ? '收起导航菜单' : '展开导航菜单'"
        @click="mobileOpen = !mobileOpen"
      >
        <AppIcon :name="mobileOpen ? 'close' : 'menu'" :size="18" />
        <span class="mobile-nav-toggle-label">{{ mobileOpen ? '收起' : '菜单' }}</span>
      </button>
    </div>
    <nav id="main-navigation" class="main-nav" aria-label="主要页面">
      <button
        v-for="([id, icon, label]) in items"
        :key="id"
        class="nav-item"
        :class="{ active: isActive(id), 'settings-nav': id === 'doctor' }"
        :aria-current="isActive(id) ? 'page' : undefined"
        type="button"
        @click="navigate(id)"
      >
        <AppIcon class="nav-icon" :name="icon" />
        <span>{{ label }}</span>
        <span v-if="id === 'history'" class="nav-count" :title="`${historyCount} 条检测记录`" :aria-label="`${historyCount} 条检测记录`">{{ displayCount(historyCount) }}</span>
      </button>
    </nav>
  </aside>
</template>

