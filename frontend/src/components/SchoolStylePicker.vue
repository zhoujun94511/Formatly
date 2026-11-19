<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { DocumentKind, School } from '../types'
import { useSchoolStyleCatalog } from '../composables/useSchoolSourceReview'
import ListPagination from './ListPagination.vue'
import ParagraphStyleOptions from './ParagraphStyleOptions.vue'

const props = defineProps<{ school: School; kind: DocumentKind; sourceId: string; modelValue?: string[]; inputId: string }>()
const emit = defineEmits<{ 'update:modelValue': [string[]] }>()
const sources = computed(() => props.school.sources.filter(item => item.kind === props.kind && item.filename.toLowerCase().endsWith('.docx')))
const catalogSource = ref('')
watch([sources, () => props.sourceId], () => {
  if (!sources.value.some(item => item.id === catalogSource.value)) catalogSource.value = sources.value.find(item => item.id === props.sourceId)?.id || sources.value[0]?.id || ''
}, { immediate: true })
const { query, page, catalog, loading, error, load } = useSchoolStyleCatalog(() => props.school, catalogSource)
const selected = computed(() => props.modelValue || [])
function toggle(identity: string, checked: boolean) {
  emit('update:modelValue', checked ? [...new Set([...selected.value, identity])] : selected.value.filter(item => item !== identity))
}
function setAdvanced(event: Event) {
  emit('update:modelValue', [...new Set((event.target as HTMLInputElement).value.split(/[,，]/).map(value => value.trim()).filter(Boolean))])
}
</script>

<template>
  <div class="school-style-picker">
    <p class="scope-label">适用段落样式</p>
    <template v-if="sources.length">
      <div class="form-group"><label :for="`${inputId}-source`">样式来源</label><select :id="`${inputId}-source`" v-model="catalogSource"><option v-for="source in sources" :key="source.id" :value="source.id">{{ source.filename }}</option></select></div>
      <div class="form-group"><label :for="`${inputId}-search`">查找样式</label><input :id="`${inputId}-search`" v-model="query" type="search" maxlength="120" placeholder="搜索名称、标识或样段" /></div>
      <p v-if="loading" class="field-help" role="status">正在读取样式…</p>
      <div v-if="error" class="notice error-notice" role="alert"><p>{{ error }}</p><button class="text-button" type="button" @click="load">重新读取样式</button></div>
      <ParagraphStyleOptions v-if="catalog" :items="catalog.items" :model-value="selected" label="来源文件中的段落样式" @update:model-value="emit('update:modelValue', $event)" />
      <p v-if="catalog && !catalog.total" class="field-help">没有匹配的样式。</p>
      <ListPagination v-if="catalog" :page="page" :total="catalog.total" :disabled="loading" label="段落样式分页" @change="page = $event" />
    </template>
    <p v-else class="field-help">此类材料还没有 DOCX 来源，可先上传模板，或填写已核对的样式标识。</p>
    <div v-if="selected.length" class="selected-styles" aria-label="已选择的样式"><button v-for="identity in selected" :key="identity" class="text-button" type="button" :aria-label="`移除样式 ${identity}`" @click="toggle(identity, false)">{{ identity }} ×</button></div>
    <p class="field-help">此处记录模板样式；检测时另行确认原稿范围。</p>
    <details class="advanced-scope"><summary>高级：填写样式标识</summary><label :for="inputId">适用样式标识</label><input :id="inputId" :value="selected.join(', ')" maxlength="2000" placeholder="用逗号分隔已核对的样式 ID" @change="setAdvanced" /></details>
    <p v-if="!selected.length" class="field-help">未指定范围时保留人工复核。</p>
  </div>
</template>

<style scoped>
.school-style-picker { margin-bottom: 18px; padding: 16px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-soft); min-width: 0; }
.scope-label { font-size: 15px; font-weight: 600; margin: 0 0 12px; }
.selected-styles { display: flex; flex-wrap: wrap; gap: 6px 12px; margin-block: 8px; }
.selected-styles button { overflow-wrap: anywhere; white-space: normal; text-align: left; }
.advanced-scope > summary { cursor: pointer; min-height: 44px; display: flex; align-items: center; font-size: 14px; }
.advanced-scope > label { display: block; font-size: 14px; margin-block: 6px; }
</style>
