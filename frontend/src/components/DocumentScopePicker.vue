<script setup lang="ts">
import { computed } from 'vue'
import type { DocumentScopeWorkspace } from '../composables/useDocumentScope'
import { displayEvidence } from '../utils/report'
import ParagraphStyleOptions from './ParagraphStyleOptions.vue'
import ListPagination from './ListPagination.vue'
const props = defineProps<{ workspace: DocumentScopeWorkspace; disabled?: boolean; hasFile: boolean }>()
const { preview, loading, error, expired, started, required, supported, requirements, active, activeIndex, query, page, styles, sections, catalogLoading, catalogError, bindings, styleIds, sectionIndices, completed, complete } = props.workspace
const selectedStyles = computed(() => active.value ? styleIds.value[active.value.id] || [] : [])
const selectedSections = computed(() => active.value ? sectionIndices.value[active.value.id] || [] : [])
const currentBinding = computed(() => active.value && bindings.value[active.value.id])
const canConfirm = computed(() => !props.disabled && !expired.value && !catalogLoading.value && !catalogError.value && (active.value?.scope_type === 'styles' ? selectedStyles.value.length : selectedSections.value.length))
function toggleSection(index: number, checked: boolean) { props.workspace.changeSections(checked ? [...new Set([...selectedSections.value, index])] : selectedSections.value.filter(item => item !== index)) }
</script>
<template>
  <section class="document-scope" aria-label="原稿范围匹配">
    <h3>原稿范围匹配</h3>
    <p v-if="!supported" class="field-help">此格式不提供 DOCX 样式与分节范围匹配，相关要求仍按报告中的人工核对或不支持项处理。</p>
    <template v-else>
      <p class="field-help">按原稿中的样段选择适用范围；模板样式不会自动套用。暂不匹配的要求保留人工核对。</p>
      <button class="button secondary" type="button" :disabled="disabled || !hasFile || loading" @click="workspace.load">{{ loading ? '正在读取原稿…' : preview ? '重新读取原稿范围' : '读取原稿范围' }}</button>
      <button v-if="started && !required" class="text-button scope-exit" type="button" :disabled="disabled" @click="workspace.exit">退出匹配，使用原方案</button>
      <p v-if="error" class="notice error-notice" role="alert">{{ error }}</p>
      <p v-if="expired" class="notice warning-notice" role="alert">原稿预览已过期，请重新读取并确认范围。</p>
      <template v-if="preview && !expired">
        <p v-for="warning in preview.warnings" :key="warning" class="field-help">{{ warning }}</p>
        <div class="scope-progress"><strong role="status">已处理 {{ completed }}/{{ requirements.length }} 条{{ complete ? '，可以开始检测' : '' }}</strong><span>每条要求须确认范围或暂不匹配。</span></div>
        <div v-if="active" class="scope-requirement">
          <div class="scope-paging"><button class="button secondary" type="button" :disabled="disabled || !activeIndex" aria-label="上一条范围要求" @click="activeIndex--">上一条</button><span>{{ activeIndex + 1 }} / {{ requirements.length }}</span><button class="button secondary" type="button" :disabled="disabled || activeIndex >= requirements.length - 1" aria-label="下一条范围要求" @click="activeIndex++">下一条</button></div>
          <h4>{{ active.label }}</h4><p class="field-help">要求值：{{ displayEvidence(active.expected) }}</p>
          <details v-if="active.source_excerpt || active.source_locator"><summary>查看学校依据</summary><p>{{ active.source_locator }}</p><blockquote>{{ active.source_excerpt }}</blockquote></details>
          <template v-if="active.scope_type === 'styles'">
            <div class="form-group scope-search"><label for="manuscript-style-search">查找原稿样式</label><input id="manuscript-style-search" v-model="query" type="search" maxlength="120" :disabled="disabled" placeholder="搜索名称、标识或样段" /></div>
            <ParagraphStyleOptions v-if="styles" :items="styles.items" :model-value="selectedStyles" :disabled="disabled || catalogLoading" used-only label="原稿中的段落样式" @update:model-value="workspace.changeStyles" />
            <p v-if="styles && !styles.total" class="field-help">没有匹配的原稿样式。</p>
            <p v-if="selectedStyles.length" class="field-help">已选样式：{{ selectedStyles.join('、') }}</p>
          </template>
          <ul v-else-if="sections" class="section-options" aria-label="原稿中的分节"><li v-for="section in sections.items" :key="section.index"><label class="checkbox-row"><input type="checkbox" :checked="selectedSections.includes(section.index)" :disabled="disabled || catalogLoading" @change="toggleSection(section.index, ($event.target as HTMLInputElement).checked)" /><span><strong>{{ section.label }}</strong><small>{{ section.paragraph_count }} 段</small></span></label><p v-for="sample in section.samples" :key="sample.location" class="field-help">{{ sample.location }}：{{ sample.text }}</p></li></ul>
          <p v-if="catalogLoading" class="field-help" role="status">正在读取范围…</p>
          <p v-if="catalogError" class="notice error-notice" role="alert">{{ catalogError }} <button class="text-button" type="button" @click="workspace.loadCatalog">重试读取范围</button></p>
          <ListPagination v-if="styles || sections" :page="page" :total="styles?.total ?? sections?.total ?? 0" :disabled="catalogLoading || disabled" label="原稿范围分页" @change="page = $event" />
          <p v-if="currentBinding" class="field-help" role="status">{{ currentBinding.status === 'bound' ? '此要求已确认适用范围。修改选择后须重新确认。' : '此要求暂不匹配，将保留人工核对。' }}</p>
          <div class="scope-actions"><button class="button primary" type="button" :disabled="!canConfirm" @click="workspace.confirm">确认此范围</button><button class="button secondary" type="button" :disabled="disabled" @click="workspace.skip">暂不匹配</button></div>
        </div>
      </template>
    </template>
  </section>
</template>
<style scoped>
.document-scope { border-top: 1px solid var(--line); margin-top: 22px; padding-top: 20px; min-width: 0; }
.scope-exit { display: block; margin-top: 12px; }
h3 { font-size: 18px; margin: 0 0 12px; } h4 { margin: 18px 0 8px; font-size: 16px; overflow-wrap: anywhere; }
.scope-progress { margin: 18px 0; display: grid; gap: 6px; font-size: 14px; } .scope-progress span { color: var(--muted); }
.scope-paging, .scope-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.scope-paging { justify-content: space-between; } .scope-actions { margin-top: 16px; }
.scope-requirement { border: 1px solid var(--line); border-radius: 8px; padding: 16px; }
.scope-search { margin-block: 14px; }
.scope-requirement > .field-help { overflow-wrap: anywhere; }
.scope-requirement details { margin-bottom: 12px; } summary { cursor: pointer; min-height: 40px; padding-block: 10px; }
blockquote { margin: 8px 0; padding: 8px 12px; border-left: 3px solid var(--line); overflow-wrap: anywhere; font-size: 14px; }
.section-options { padding: 0; list-style: none; max-height: 380px; overflow: auto; } .section-options > li { padding: 10px 0; border-bottom: 1px solid var(--line); }
@media (max-width: 520px) { .scope-requirement { padding: 12px; } .scope-actions > button { flex: 1 1 140px; } }
</style>
