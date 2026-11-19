<script setup lang="ts">
import { computed } from 'vue'
import type { SchoolTargetField } from '../utils/profileFields'

const props = defineProps<{ modelValue: string; target: string; mode: string; inputId: string; fieldMode?: string; metadata?: SchoolTargetField }>()
const emit = defineEmits<{ 'update:modelValue': [string]; 'update:fieldMode': [string] }>()
const value = computed({ get: () => props.modelValue, set: (next: string | number) => emit('update:modelValue', String(next)) })
const isField = computed(() => props.mode === 'automatic' && props.target.startsWith('field.'))
const empty = (text: string) => !text.trim() || text.trim() === 'null'
const fieldChoice = computed(() => props.fieldMode || (empty(props.modelValue) ? 'required' : 'fixed'))
function setFieldMode(event: Event) {
  const choice = (event.target as HTMLSelectElement).value
  emit('update:fieldMode', choice)
  if (choice === 'required') emit('update:modelValue', '')
}
const numeric = computed(() => props.mode === 'automatic' && /^page\.|^body\.(size_pt|line_spacing)$|^references\.(heading_after_lines|entry_hanging_chars)$|^paragraph\.(first_line_indent_chars|before_lines|after_lines|line_spacing_pt)$|^headings\.[1-9]\.(size_pt|before_lines|after_lines)$|^section\.(gutter_mm|header_distance_mm|footer_distance_mm|columns)$/.test(props.target))
const schemaOptions = computed(() => Array.isArray(props.metadata?.value_schema.enum) ? props.metadata.value_schema.enum : [])
const choices = computed(() => props.metadata?.options || schemaOptions.value.map(value => ({ value: String(value), label: String(value) })))
const constants = computed(() => props.metadata?.const_options || (Array.isArray(props.metadata?.value_schema.anyOf) ? (props.metadata.value_schema.anyOf as Record<string, unknown>[]).filter(schema => 'const' in schema).map(schema => ({ value: String(schema.const), label: String(schema.const) })) : []))
const constantChoice = computed(() => constants.value.some(option => option.value === props.modelValue) ? props.modelValue : '')
function chooseConstant(event: Event) { value.value = (event.target as HTMLSelectElement).value }
</script>

<template>
  <div class="form-group requirement-value">
    <template v-if="isField">
      <label :for="`${inputId}-field-mode`">字段要求</label>
      <select :id="`${inputId}-field-mode`" :value="fieldChoice" @change="setFieldMode"><option value="required">必须填写，不限定具体内容</option><option value="fixed">必须与指定值一致</option></select>
      <template v-if="fieldChoice === 'fixed'"><label :for="inputId">指定值</label><input :id="inputId" v-model="value" type="text" maxlength="120" :aria-invalid="empty(modelValue)" placeholder="填写实际要求的姓名、单位或日期等内容" /><p class="field-help">仅在学校明确限定具体内容时使用；日期填写为 YYYY-MM-DD。</p></template>
      <p v-else class="field-help">检查是否填写了明确且唯一的字段值，无需输入“必填”等说明。</p>
    </template>
    <template v-else>
      <label :for="inputId">{{ mode === 'manual' ? '人工核对内容' : '要求值' }}</label>
      <template v-if="mode === 'automatic' && constants.length"><select :id="`${inputId}-mode`" :value="constantChoice" :aria-label="`${metadata?.label || '要求值'}设置方式`" @change="chooseConstant"><option value="">指定数值</option><option v-for="option in constants" :key="option.value" :value="option.value">{{ option.label }}</option></select><input v-if="!constantChoice" :id="inputId" v-model="value" type="number" step="1" inputmode="numeric" /></template>
      <select v-else-if="mode === 'automatic' && metadata?.type === 'boolean'" :id="inputId" v-model="value"><option value="">请选择</option><option value="true">启用检查</option><option value="false">关闭检查</option></select>
      <select v-else-if="mode === 'automatic' && metadata?.type === 'select'" :id="inputId" v-model="value"><option value="">请选择</option><option v-for="option in choices" :key="option.value" :value="option.value">{{ option.label }}</option></select>
      <input v-else-if="numeric || mode === 'automatic' && metadata?.type === 'number'" :id="inputId" v-model="value" type="number" step="any" inputmode="decimal" />
      <select v-else-if="mode === 'automatic' && target === 'references.citation_unique'" :id="inputId" v-model="value"><option value="true">不得重复引用</option><option value="false">允许重复引用</option></select>
      <select v-else-if="mode === 'automatic' && /^headings\.[1-9]\.alignment$/.test(target)" :id="inputId" v-model="value"><option value="left">左对齐</option><option value="center">居中</option><option value="right">右对齐</option><option value="both">两端对齐</option><option value="distribute">分散对齐</option></select>
      <select v-else-if="mode === 'automatic' && target === 'references.citation_order'" :id="inputId" v-model="value"><option value="ascending">按首次引用顺序递增</option></select>
      <textarea v-else :id="inputId" v-model="value" rows="2" maxlength="12000" />
      <p v-if="mode === 'automatic' && metadata?.type === 'boolean'" class="field-help">关闭表示不执行此项检查，报告不会把关闭的检查计为通过。</p>
    </template>
  </div>
</template>

<style scoped>
.requirement-value > select + label { display: block; margin-top: 12px; }
</style>
