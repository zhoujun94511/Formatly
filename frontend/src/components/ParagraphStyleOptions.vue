<script setup lang="ts">
import type { ParagraphStyleChoice } from '../types'
const props = defineProps<{ items: ParagraphStyleChoice[]; modelValue: string[]; disabled?: boolean; usedOnly?: boolean; label: string }>()
const emit = defineEmits<{ 'update:modelValue': [string[]] }>()
function toggle(id: string, checked: boolean) { emit('update:modelValue', checked ? [...new Set([...props.modelValue, id])] : props.modelValue.filter(value => value !== id)) }
</script>
<template>
  <ul class="style-options" :aria-label="label">
    <li v-for="style in items" :key="style.id">
      <label class="checkbox-row"><input type="checkbox" :aria-label="`${style.name}（${style.id}），${style.paragraph_count} 段`" :disabled="disabled || usedOnly && !style.paragraph_count" :checked="modelValue.includes(style.id)" @change="toggle(style.id, ($event.target as HTMLInputElement).checked)" /><span><strong>{{ style.name }}</strong><small>{{ style.id }} · {{ style.paragraph_count }} 段{{ style.declared ? '' : ' · 未定义样式' }}</small></span></label>
      <p v-if="usedOnly && !style.paragraph_count" class="style-sample">原稿未使用此样式，不能作为检测范围。</p>
      <p v-for="sample in style.samples" :key="sample.location" class="style-sample"><span>{{ sample.location }}</span>{{ sample.text }}</p>
    </li>
  </ul>
</template>
<style scoped>
.style-options { padding: 0; list-style: none; max-height: 380px; overflow: auto; }
.style-options > li { padding: 10px 0; border-bottom: 1px solid var(--line); }
.checkbox-row span { min-width: 0; overflow-wrap: anywhere; }
.style-sample { font-size: 14px; margin: 6px 0 0 28px; color: var(--muted); overflow-wrap: anywhere; }
.style-sample span { display: block; font-size: 12px; }
</style>
