<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })
const paths: Record<string, string[]> = {
  file: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z', 'M14 2v6h6M8 13h8M8 17h5'],
  upload: ['M12 16V3M7 8l5-5 5 5', 'M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4'],
  plus: ['M12 5v14M5 12h14'],
  check: ['M5 12l4 4L19 6'],
  'arrow-right': ['M4 12h16M14 6l6 6-6 6'],
  'chevron-right': ['m9 5 7 7-7 7'],
  'chevron-down': ['m6 9 6 6 6-6'],
  settings: ['M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8', 'm9 3-1 3-3 1-2 3 2 2v3l3 2 1 4h5l1-4 3-2v-3l2-2-2-3-3-1-1-3Z'],
  history: ['M3 11a9 9 0 1 1 2 7M3 4v7h7', 'M12 7v5l3 2'],
  school: ['m3 8 9-5 9 5-9 5Z', 'M6 10v7l6 4 6-4v-7M21 8v8'],
  refresh: ['M20 7v5h-5M4 17v-5h5', 'M6 7a7 7 0 0 1 11-2l3 3M4 16l3 3a7 7 0 0 0 11-2'],
  close: ['m6 6 12 12M6 18 18 6'],
  menu: ['M4 6h16M4 12h16M4 18h16'],
  search: ['M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15M16 16l5 5'],
  layers: ['m12 3 10 5-10 5L2 8Z', 'm2 12 10 5 10-5M2 16l10 5 10-5'],
  download: ['M12 3v13m-5-5 5 5 5-5', 'M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4'],
  copy: ['M9 9h12v12H9Z', 'M15 5V3H3v12h2'],
  alert: ['m12 3 10 18H2Z', 'M12 9v5M12 17h.01'],
  sun: ['M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8', 'M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5'],
  moon: ['M20.5 13A8.5 8.5 0 0 1 11 3.5a8.5 8.5 0 1 0 9.5 9.5Z'],
}
</script>
<template>
  <svg class="app-icon" xmlns="http://www.w3.org/2000/svg" :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path v-for="(path, index) in (paths[name] || paths.file)" :key="index" :d="path" /></svg>
</template>
<style scoped>
.app-icon { display: inline-block; flex: none; vertical-align: middle; }
</style>
