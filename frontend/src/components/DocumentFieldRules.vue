<script setup lang="ts">
import { computed, ref } from 'vue'
import { settingsObject, updateDocumentFieldRules, type DocumentFieldOptions } from '../utils/profileFields'
const props = defineProps<{ modelValue: string; metadata: DocumentFieldOptions; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [string] }>()
const error = ref('')
const fields = computed(() => {
  try {
    const value = settingsObject(props.modelValue).fields
    return value === undefined ? {} : value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
  } catch { return null }
})
const selected = computed(() => Array.isArray(fields.value?.required) ? fields.value.required as string[] : [])
function update(patch: { required?: string[]; missing_policy?: string }) {
  try { emit('update:modelValue', updateDocumentFieldRules(props.modelValue, props.metadata, patch)); error.value = '' }
  catch (value) { error.value = value instanceof Error ? value.message : String(value) }
}
function toggle(value: string, checked: boolean) { update({ required: checked ? [...selected.value, value] : selected.value.filter(item => item !== value) }) }
</script>
<template>
  <fieldset class="document-field-rules" :disabled="disabled || !fields">
    <legend>必填字段</legend>
    <p v-if="!fields" class="notice error-notice" role="alert">请先修正高级参数中的 fields 对象。</p>
    <p v-if="error" class="notice error-notice" role="alert">{{ error }}</p>
    <div class="field-options"><label v-for="option in metadata.field_options" :key="option.value" class="checkbox-row"><input type="checkbox" :checked="selected.includes(option.value)" @change="toggle(option.value, ($event.target as HTMLInputElement).checked)" />{{ option.label }}</label></div>
    <div class="form-group"><label for="field-missing-policy">缺项处理</label><select id="field-missing-policy" :value="fields?.missing_policy || 'review'" aria-describedby="field-missing-policy-help" @change="update({ missing_policy: ($event.target as HTMLSelectElement).value })"><option v-for="option in metadata.missing_policies" :key="option.value" :value="option.value">{{ option.label }}</option></select><p id="field-missing-policy-help" class="field-help">{{ metadata.missing_policy_help }}</p></div>
  </fieldset>
</template>
<style scoped>
.document-field-rules { border: 0; border-top: 1px solid var(--line); padding: 14px 0 0; margin-top: 14px; min-width: 0; }
legend { font-size: 16px; font-weight: 700; padding-right: 8px; }
.field-options { display: flex; flex-wrap: wrap; gap: 12px 20px; margin-block: 10px 18px; }
.field-options label { margin: 0; }
</style>
