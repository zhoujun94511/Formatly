<script setup lang="ts">
import { computed } from 'vue'
import { useDocumentCapabilities } from '../composables/useDocumentCapabilities'

const state = useDocumentCapabilities()
const { capabilities, loading, error } = state
const needsAttention = computed(() => !!error.value || !!capabilities.value && !capabilities.value.pdf.available)
const status = computed(() => loading.value ? '检查中…' : error.value ? '读取失败' : needsAttention.value ? '需检查' : !capabilities.value ? '' : capabilities.value.ocr.available ? '可用' : '文本 PDF 可读')
const languageNames: Record<string, string> = {
  chi_sim: '简体中文', chi_tra: '繁体中文', chi_sim_vert: '竖排简体中文', chi_tra_vert: '竖排繁体中文',
  eng: '英语', jpn: '日语', kor: '韩语', fra: '法语', deu: '德语', spa: '西班牙语',
  por: '葡萄牙语', rus: '俄语', ara: '阿拉伯语', hin: '印地语',
}
const languageCodes = computed(() => [...new Set(capabilities.value?.ocr.languages || [])])
const knownLanguages = computed(() => languageCodes.value.filter(code => languageNames[code]).map(code => languageNames[code]))
const otherLanguages = computed(() => languageCodes.value.filter(code => !languageNames[code] && code !== 'osd'))
</script>
<template>
  <details class="document-capabilities" :open="needsAttention" :aria-busy="loading">
    <summary>PDF 识别状态 <span class="muted">{{ status }}</span></summary>
    <p v-if="loading" class="field-help" role="status">正在检查…</p>
    <p v-else-if="error" class="notice warm-notice" role="alert">{{ error }}</p>
    <template v-else-if="capabilities">
      <p class="field-help">文本读取：{{ capabilities.pdf.available ? '可用' : '未配置' }} · 扫描件识别：{{ capabilities.ocr.available ? '可用' : '未配置' }}</p>
      <template v-if="capabilities.ocr.available">
        <p v-if="knownLanguages.length" class="field-help">可用识别语言：{{ knownLanguages.join('、') }}</p>
        <details v-if="otherLanguages.length || languageCodes.includes('osd')" class="language-details"><summary>其他识别数据</summary><p v-for="code in otherLanguages" :key="code" class="field-help">其他语言（{{ code }}）</p><p v-if="languageCodes.includes('osd')" class="field-help">版面方向识别（osd）</p></details>
      </template>
      <p v-if="!capabilities.pdf.available" class="notice warm-notice">PDF 读取不可用。<a href="#doctor">打开设置 → 运行环境</a></p>
      <p v-if="!capabilities.ocr.available" class="field-help">扫描件识别未配置。<a href="#doctor">打开运行环境</a></p>
    </template>
    <button type="button" class="text-button" :disabled="loading" @click="state.refresh">{{ error ? '重试' : '重新检查' }}</button>
  </details>
</template>

<style scoped>
.document-capabilities { margin-top: 16px; padding-top: 4px; border-top: 1px solid var(--line); }
a { color: var(--brand); font-weight: 700; }
summary { min-height: 44px; padding-block: 10px; cursor: pointer; font-size: 15px; }
summary span { margin-left: 8px; font-size: 13px; }
summary:focus-visible { outline: 3px solid var(--brand); outline-offset: 3px; border-radius: 6px; }
.text-button { min-height: 44px; }
</style>
