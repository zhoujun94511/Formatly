<script setup lang="ts">
import type { PagePreview } from '../utils/reportWorkspace'
const props = defineProps<{ preview: PagePreview }>()
function boxStyle(box: number[]) {
  const page = props.preview
  return { left: `${box[0] / page.width_pt * 100}%`, top: `${box[1] / page.height_pt * 100}%`, width: `${(box[2] - box[0]) / page.width_pt * 100}%`, height: `${(box[3] - box[1]) / page.height_pt * 100}%` }
}
</script>
<template>
  <figure class="page-evidence"><div class="page-preview"><img :src="preview.image_url" :alt="`原稿第 ${preview.page} 页`" /><span v-for="(box, index) in preview.boxes" :key="index" class="evidence-box" :style="boxStyle(box)" aria-hidden="true" /></div><figcaption>第 {{ preview.page }} 页<span v-if="preview.boxes.length">；标记来自该页实际文字坐标</span>。</figcaption></figure>
</template>
<style scoped>
.page-evidence { margin: 16px 0; }
.page-preview { position: relative; line-height: 0; }
.page-preview img { display: block; width: 100%; height: auto; }
.evidence-box { position: absolute; border: 2px solid #c53826; background: #ffcc0040; pointer-events: none; }
figcaption { color: var(--muted); font-size: 14px; margin-top: 8px; }
</style>
