<script setup lang="ts">
import { computed } from 'vue'
import type { DocumentExtraction, DocumentFormat } from '../types'
import { extractionMethodLabel, formatLabel } from '../utils/documents'
import { usePagedItems } from '../composables/usePagedItems'
import ListPagination from './ListPagination.vue'

const props = defineProps<{ extraction?: DocumentExtraction; format?: DocumentFormat; method?: string; canLocateOcr?: boolean; complete?: boolean }>()
const emit = defineEmits<{ locateOcr: [string] }>()
const pages = computed(() => props.extraction?.pages || [])
const { page: pageIndex, displayed: visiblePages, setPage } = usePagedItems(pages)
const review = computed(() => props.extraction?.ocr_review)
const pageCount = computed(() => props.extraction?.page_count ?? pages.value.length)
const method = computed(() => {
  if (props.method || props.extraction?.text_method || props.extraction?.method) return extractionMethodLabel(props.method || props.extraction?.text_method || props.extraction?.method)
  const methods = [...new Set(pages.value.map(page => page.method).filter(Boolean))]
  return methods.length ? methods.map(extractionMethodLabel).join('、') : '文本读取'
})
const size = (value?: number) => typeof value === 'number' ? `${value.toFixed(1)} 毫米` : '未记录'
const reviewReasons: Record<string, string> = {
  time_limit: '本次复核已达到时间上限', line_limit: '本次复核已达到行数上限',
  crop_limit: '该行无法取得有效图像', text_limit: '该行超出可复核长度',
  no_single_line: '未能取得单行识别结果', recognition_unavailable: '补充识别未完成',
  observation_limit: '本次复核已达到记录上限',
}
const reviewReason = (reason?: string) => reviewReasons[reason || ''] || '未完成补充识别'
</script>
<template>
  <div class="document-extraction">
    <p class="field-help">{{ formatLabel(format || extraction?.format) }} · {{ method }}<span v-if="pageCount"> · {{ pageCount }} 页</span></p>
    <p v-if="extraction?.complete === false" class="notice warm-notice">提取未完成<span v-if="extraction.processed_pages !== undefined">，已处理 {{ extraction.processed_pages }} / {{ pageCount || '未记录' }} 页</span>，请对照原件复核。</p>
    <p v-if="extraction?.requires_review && extraction.complete !== false" class="notice warm-notice">识别结果需对照原件复核。</p>
    <p v-for="warning in extraction?.warnings" :key="warning" class="notice warm-notice">{{ warning }}</p>
    <details v-if="review" class="ocr-review" :open="complete">
      <summary>识别复核<span v-if="review.disagreement_count"> · {{ review.disagreement_count }} 处有分歧</span><span v-if="review.not_checked_count"> · {{ review.not_checked_count }} 处未完成</span></summary>
      <p v-if="!review.observations.length" class="field-help">补充识别的 {{ review.consistent_count }} 行未发现分歧，仍需对照原件核对。</p>
      <ol v-else class="ocr-observations">
        <li v-for="(observation, index) in review.observations" :key="index">
          <strong>{{ observation.location || `第 ${observation.page ?? '—'} 页` }}</strong>
          <button v-if="canLocateOcr && observation.location" type="button" class="text-button locate-ocr" @click="emit('locateOcr', observation.location)">查看原页</button>
          <dl>
            <div><dt>首次识别</dt><dd>{{ observation.primary_text }}</dd></div>
            <div v-if="observation.alternative"><dt>补充识别</dt><dd>{{ observation.alternative.text }}</dd></div>
          </dl>
          <p v-if="observation.status === 'not_checked'" class="field-help">{{ reviewReason(observation.reason) }}</p>
          <p v-else-if="observation.status === 'consistent'" class="field-help">两次识别一致，仍需核对。</p>
        </li>
      </ol>
      <p v-if="review.truncated" class="field-help">此处显示前 40 处，完整记录见文档提取证据。</p>
    </details>
    <details v-if="pages.length" :open="complete"><summary>页面信息</summary><ListPagination v-if="!complete" :page="pageIndex" :total="pages.length" label="页面信息分页" @change="setPage" /><ul class="extraction-pages"><li v-for="(page, index) in complete ? pages : visiblePages" :key="page.number ?? index">第 {{ page.number ?? (complete ? index + 1 : (pageIndex - 1) * 10 + index + 1) }} 页 · {{ extractionMethodLabel(page.method) }} · {{ size(page.width_mm) }} × {{ size(page.height_mm) }}<span v-if="typeof page.confidence === 'number'"> · 识别置信度 {{ page.confidence.toFixed(1) }} / 100</span></li></ul></details>
  </div>
</template>
<style scoped>
.extraction-pages { padding-left: 1.3rem; color: var(--muted); overflow-wrap: anywhere; }
.extraction-pages li { margin-block: .4rem; }
.ocr-review { margin-block: 1rem; }
.locate-ocr { margin-inline-start: 12px; }
.ocr-observations { padding-left: 1.3rem; }
.ocr-observations li { margin-block: 1rem; overflow-wrap: anywhere; }
.ocr-observations dl { margin-block: .5rem; }
.ocr-observations dl > div { display: grid; grid-template-columns: 5rem minmax(0, 1fr); gap: .5rem; margin-block: .4rem; }
.ocr-observations dt { color: var(--muted); }
.ocr-observations dd { margin: 0; white-space: pre-wrap; min-width: 0; }
@media (max-width: 480px) { .ocr-observations dl > div { grid-template-columns: minmax(0, 1fr); gap: .2rem; } }
</style>
