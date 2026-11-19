<script setup lang="ts">
import type { WorkspaceWarning } from '../types'
defineProps<{ warnings: WorkspaceWarning[]; label: string }>()
</script>
<template>
  <details v-if="warnings.length" class="notice warm-notice" role="status">
    <summary>{{ warnings.length }} 份{{ label }}未加载</summary>
    <p v-for="warning in warnings" :key="warning.file">{{ warning.file }}：{{ warning.message }}</p>
  </details>
</template>
