<script setup lang="ts">
import { ref } from 'vue'
import Sidebar from './Sidebar.vue'
import Topbar from './Topbar.vue'
import type { Page } from '../types'

defineProps<{ page: Page; title: string; historyCount: number; loading?: boolean }>()
const emit = defineEmits<{ navigate: [Page]; refresh: [] }>()
const mainContent = ref<HTMLElement>()

function skipToMain() {
  mainContent.value?.focus({ preventScroll: true })
  window.scrollTo({ top: 0, behavior: 'auto' })
}
</script>

<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-content" @click.prevent="skipToMain">跳到主要内容</a>
    <Sidebar :page="page" :history-count="historyCount" @navigate="emit('navigate', $event)" />
    <div class="workspace">
      <Topbar :title="title" :loading="loading" @refresh="emit('refresh')" />
      <main id="main-content" ref="mainContent" tabindex="-1"><slot /></main>
    </div>
  </div>
</template>

