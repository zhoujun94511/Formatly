<script setup lang="ts">
import { ref } from 'vue'
const props = defineProps<{ modelValue?: number[]; inputId: string; allowGlobal?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [number[]] }>()
const next = ref(''), error = ref('')
function add() {
  const value = Number(next.value)
  if (!next.value.trim() || !Number.isSafeInteger(value) || value < 1 || value > 1000) { error.value = '请填写 1 至 1000 的整数分节编号。'; return }
  emit('update:modelValue', [...new Set([...(props.modelValue || []), value])].sort((a, b) => a - b)); next.value = ''; error.value = ''
}
</script>
<template>
  <div class="section-scope">
    <label :for="inputId">模板分节范围</label><p class="field-help">{{ allowGlobal ? '留空适用于全部分节。' : '留空保留人工核对。' }}指定模板分节后，检测原稿时仍须重新选择原稿分节。</p>
    <div class="section-add form-group"><input :id="inputId" v-model="next" type="number" min="1" max="1000" step="1" inputmode="numeric" placeholder="从 1 开始" :aria-invalid="!!error" /><button class="button secondary" type="button" @click="add">添加分节</button></div>
    <p v-if="error" class="field-help" role="alert">{{ error }}</p>
    <div v-if="modelValue?.length" class="section-chips" aria-label="已选择的模板分节"><button v-for="index in modelValue" :key="index" class="text-button" type="button" :aria-label="`移除模板第 ${index} 节`" @click="emit('update:modelValue', modelValue.filter(item => item !== index))">第 {{ index }} 节 ×</button></div>
  </div>
</template>
<style scoped>
.section-scope { margin-block: 16px; padding: 14px; border: 1px solid var(--line); border-radius: 8px; }
.section-scope > label { font-size: 15px; font-weight: 600; } .section-add { display: flex; gap: 10px; align-items: center; } .section-add input { min-width: 0; flex: 1; } .section-chips { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 10px; }
@media (max-width: 420px) { .section-add { flex-wrap: wrap; } .section-add input { flex-basis: 100%; } }
</style>
