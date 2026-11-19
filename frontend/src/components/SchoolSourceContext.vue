<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Requirement, School } from '../types'
import { useSchoolSourceContext } from '../composables/useSchoolSourceReview'

const props = defineProps<{ school: School; requirement: Pick<Requirement, 'id' | 'source_id' | 'source_locator' | 'source_excerpt'> | null }>()
const { context, loading, error, load } = useSchoolSourceContext(() => props.school, () => props.requirement)
const source = computed(() => props.school.sources.find(item => item.id === props.requirement?.source_id))
const expanded = ref(false)
const panel = ref<HTMLElement>()
watch(() => props.requirement?.id, () => { expanded.value = false })
function show() { expanded.value = true; panel.value?.focus({ preventScroll: true }); panel.value?.scrollIntoView({ block: 'nearest', behavior: 'auto' }) }
defineExpose({ show })
const parts = computed(() => {
  const value = context.value, anchor = value?.matched_excerpt
  if (!value || !anchor) return [value?.text || '', '', '']
  const position = value.text.indexOf(anchor)
  return position < 0 ? [value.text, '', ''] : [value.text.slice(0, position), anchor, value.text.slice(position + anchor.length)]
})
</script>

<template>
  <aside ref="panel" class="school-source-context" aria-label="当前要求的来源对照" tabindex="-1">
    <h3 class="source-context-heading">来源对照</h3>
    <button class="source-context-toggle" type="button" :aria-expanded="expanded" aria-controls="school-source-context-body" @click="expanded = !expanded">来源对照<span>{{ expanded ? '收起' : '展开' }}</span></button>
    <div id="school-source-context-body" class="source-context-body" :class="{ expanded }">
      <template v-if="requirement && source">
        <h3>{{ source.filename }}</h3><p class="field-help">{{ requirement.source_locator || '尚未填写出处' }}</p>
        <p v-if="loading" role="status">正在读取来源…</p>
        <div v-else-if="error" class="notice error-notice" role="alert"><p>{{ error }}</p><button class="text-button" type="button" @click="load">重新读取来源</button></div>
        <template v-else-if="context">
          <p class="context-location">{{ context.location }}</p><pre class="source-context-text">{{ parts[0] }}<mark v-if="parts[1]">{{ parts[1] }}</mark>{{ parts[2] }}</pre>
          <p v-if="!context.text" class="field-help">来源没有可读取文本，请下载原件核对。</p>
          <p v-else-if="!context.match_found" class="field-help">未在提取文本中匹配摘录，请结合原件核对。</p>
          <p v-if="context.truncated" class="field-help">当前仅展示相关片段。</p>
        </template>
        <a class="text-button" :href="`/api/schools/${encodeURIComponent(school.id)}/sources/${encodeURIComponent(source.id)}`" download>下载来源原件</a>
      </template>
      <p v-else class="field-help">展开一条要求，查看对应来源。</p>
    </div>
  </aside>
</template>

<style scoped>
.school-source-context { min-width: 0; border: 1px solid var(--line); border-radius: 10px; background: var(--surface-soft); align-self: start; position: sticky; top: 88px; }
.source-context-heading { margin: 0; border-bottom: 1px solid var(--line); font-size: 16px; padding: 14px 16px; }
.source-context-toggle { display: none; justify-content: space-between; gap: 12px; width: 100%; border: 0; border-bottom: 1px solid var(--line); background: transparent; color: var(--ink); font: inherit; font-weight: 600; padding: 14px 16px; text-align: left; }
.source-context-toggle > span { display: none; }
.source-context-body { padding: 16px; }
.source-context-body h3 { margin: 0; font-size: 15px; overflow-wrap: anywhere; }
.source-context-text { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; font-size: 14px; line-height: 1.8; max-height: min(60vh, 680px); overflow: auto; margin: 12px 0; }
.context-location { font-size: 13px; color: var(--muted); }
mark { background: var(--warning-bg); color: var(--ink); padding: 1px 0; }
@container workspace (max-width: 1100px) { .school-source-context { position: static; } .source-context-heading { display: none; } .source-context-toggle { display: flex; cursor: pointer; min-height: 44px; } .source-context-toggle > span { display: inline; color: var(--brand); font-size: 14px; } .source-context-body { display: none; } .source-context-body.expanded { display: block; } }
</style>
