<script setup lang="ts">
import { computed, ref } from 'vue'
import { fieldValue, settingsObject, updateRuleField, type RuleField } from '../utils/profileFields'

const props = defineProps<{ modelValue: string; fields: RuleField[]; disabled?: boolean; collapsible?: boolean; idPrefix?: string }>()
const emit = defineEmits<{ 'update:modelValue': [string] }>()
const error = ref('')
const settings = computed(() => { try { return settingsObject(props.modelValue) } catch { return null } })
const groups = computed(() => [...new Set(props.fields.map(field => field.group))])
const inputId = (field: RuleField) => `${props.idPrefix || 'rule'}-${field.path}`
function value(field: RuleField) { const result = settings.value ? fieldValue(settings.value, field.path) : undefined; return Array.isArray(result) ? result.join('\n') : typeof result === 'boolean' ? String(result) : typeof result === 'number' || typeof result === 'string' ? result : '' }
const constants = (field: RuleField) => field.const_options || []
const constantChoice = (field: RuleField) => constants(field).some(option => option.value === String(value(field))) ? String(value(field)) : ''
function update(field: RuleField, event: Event) {
  try { emit('update:modelValue', updateRuleField(props.modelValue, field, (event.target as HTMLInputElement).value)); error.value = '' }
  catch (failure) {
    error.value = failure instanceof Error ? failure.message : String(failure)
    // A rejected edit must not remain visible as if it were the saved setting.
    const input = event.target as HTMLInputElement
    input.value = String(value(field))
  }
}
</script>

<template>
  <div class="rule-fields">
    <p v-if="!settings" class="notice error-notice" role="alert">请先修正高级参数中的 JSON，再编辑常用规则。</p>
    <p v-if="error" class="notice error-notice" role="alert">{{ error }}</p>
    <component :is="collapsible ? 'details' : 'div'" v-for="group in groups" :key="group" class="rule-group" :class="{ 'collapsible-group': collapsible }">
      <summary v-if="collapsible">{{ group }}</summary>
      <fieldset :disabled="disabled || !settings" class="rule-fieldset">
      <legend :class="{ 'visually-hidden': collapsible }">{{ group }}</legend>
      <div class="form-grid">
        <div v-for="field in fields.filter(item => item.group === group)" :key="field.path" class="form-group" :class="{ 'wide-field': field.type === 'lines' }">
          <label :for="inputId(field)">{{ field.label }} <span v-if="field.unit" class="optional-label">{{ field.unit }}</span></label>
          <template v-if="constants(field).length"><select :id="inputId(field)" :value="constantChoice(field)" :aria-describedby="field.help ? `${inputId(field)}-help` : undefined" @change="update(field, $event)"><option value="">指定数值</option><option v-for="option in constants(field)" :key="option.value" :value="option.value">{{ option.label }}</option></select><input v-if="!constantChoice(field)" :id="`${inputId(field)}-number`" :value="value(field)" type="number" :step="field.integer ? '1' : 'any'" :min="field.minimum ?? field.exclusiveMinimum" :max="field.maximum" :aria-label="`${field.label}指定数值`" @change="update(field, $event)" /></template>
          <textarea v-else-if="field.type === 'lines'" :id="inputId(field)" :value="value(field)" rows="2" :placeholder="field.placeholder" :aria-describedby="field.help ? `${inputId(field)}-help` : undefined" @change="update(field, $event)" />
          <select v-else-if="field.type === 'select' || field.type === 'boolean'" :id="inputId(field)" :value="value(field)" :aria-describedby="field.help ? `${inputId(field)}-help` : undefined" @change="update(field, $event)">
            <option value="">不设置</option>
            <template v-if="field.type === 'boolean'"><option value="true">启用</option><option value="false">关闭</option></template>
            <option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
          <input v-else :id="inputId(field)" :value="value(field)" :type="field.type === 'number' ? 'number' : 'text'" :step="field.type === 'number' ? (field.integer ? '1' : 'any') : undefined" :min="field.minimum ?? field.exclusiveMinimum" :max="field.maximum" :placeholder="field.placeholder || '不设置'" :aria-describedby="field.help ? `${inputId(field)}-help` : undefined" @change="update(field, $event)" />
          <p v-if="field.help" :id="`${inputId(field)}-help`" class="field-help">{{ field.help }}</p>
        </div>
      </div>
      </fieldset>
    </component>
  </div>
</template>

<style scoped>
.rule-fieldset { border: 0; border-top: 1px solid var(--line); padding: 14px 0 0; margin: 12px 0 0; min-width: 0; }
legend { padding: 0 8px 0 0; font-size: 16px; font-weight: 700; }
.wide-field { grid-column: 1 / -1; }
.collapsible-group { margin-top: 12px; border: 1px solid var(--line); border-radius: 8px; }
.collapsible-group > summary { padding: 12px 14px; cursor: pointer; font-weight: 600; }
.collapsible-group > summary:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
.collapsible-group .rule-fieldset { margin: 0; padding: 0 14px 14px; border: 0; }
</style>
