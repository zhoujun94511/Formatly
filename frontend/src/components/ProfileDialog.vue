<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import type { Plugin, Profile } from '../types'
import { automaticTargets, profileLabel } from '../utils/materials'
import { displayRuleEvidence, engineLabel } from '../utils/report'
import { profileCopy, profilePlugins, schoolRulesChanged } from '../utils/profileCopy'
import RuleFields from './RuleFields.vue'
import DocumentFieldRules from './DocumentFieldRules.vue'
import { profileChanges, settingsObject, type RuleField, type RuleFieldGroup, type DocumentFieldOptions } from '../utils/profileFields'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ open: boolean; source: Profile | null; plugins: Plugin[]; fields?: RuleField[]; academicFields?: RuleFieldGroup; structureFields?: RuleFieldGroup; documentFields?: DocumentFieldOptions; fieldsError?: string; importing?: boolean; saving?: boolean; saveError?: string }>()
const emit = defineEmits<{ close: []; save: [Omit<Profile, 'id'> & { id: string }] }>()
const dialog = ref<HTMLDialogElement>()
const nameInput = ref<HTMLInputElement>()
const form = reactive({ id: '', name: '', description: '', settings: '{}', plugins: [] as string[] })
const formError = ref('')
const changes = computed(() => { try { return props.source ? profileChanges(props.source, settingsObject(form.settings), form.plugins) : [] } catch { return [] } })
function changeValue(path: string, raw: string) {
  try {
    const value: unknown = JSON.parse(raw)
    if (path === 'plugins' && Array.isArray(value)) return value.map(id => engineLabel(String(id), props.plugins.find(plugin => plugin.id === id)?.name)).join('、')
    return displayRuleEvidence(value, path)
  } catch { return raw }
}
const genericEnabled = computed(() => form.plugins.includes('generic-format'))
const academicEnabled = computed(() => !!props.academicFields && form.plugins.includes(props.academicFields.plugin_id))
const structureEnabled = computed(() => !!props.structureFields && form.plugins.includes(props.structureFields.plugin_id))
const editableFields = computed(() => [...(props.fields || []), ...(props.academicFields?.fields || []), ...(props.structureFields?.fields || [])])
const becomesCustom = computed(() => {
  try { return !!props.source && schoolRulesChanged(props.source, JSON.parse(form.settings), form.plugins) }
  catch { return false }
})
const availablePlugins = computed(() => {
  const ids = [...new Set(['docx-package', ...props.plugins.map(p => p.id), ...(props.source?.plugins || [])])]
  return ids.map(id => props.plugins.find(p => p.id === id) || { id, name: engineLabel(id) })
})
watch(() => props.open, async open => {
  if (open && props.source) {
    form.id = `${props.source.id.replace(/[^a-z0-9-]/g, '-').slice(0, 40)}-copy-${Date.now().toString(36)}`
    form.name = `${props.source.name}（${props.importing ? '导入' : '副本'}）`
    form.description = props.source.description || ''
    form.settings = JSON.stringify(props.source.settings || {}, null, 2)
    form.plugins = profilePlugins(props.source)
    formError.value = ''
    await nextTick()
    dialog.value?.showModal()
    nameInput.value?.focus()
  } else if (!open) dialog.value?.close()
})
onBeforeUnmount(() => dialog.value?.close())
function close() { if (!props.saving) emit('close') }
function trapFocus(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !dialog.value) return
  const controls = Array.from(dialog.value.querySelectorAll<HTMLElement>('button, input, select, textarea, [tabindex]'))
    .filter(element => !element.matches(':disabled') && element.tabIndex >= 0 && element.getClientRects().length > 0)
  const first = controls[0], last = controls[controls.length - 1]
  if (!first || !last) { event.preventDefault(); return }
  if (event.shiftKey && (document.activeElement === first || !dialog.value.contains(document.activeElement))) {
    event.preventDefault(); last.focus()
  } else if (!event.shiftKey && (document.activeElement === last || !dialog.value.contains(document.activeElement))) {
    event.preventDefault(); first.focus()
  }
}
function save() {
  if (props.saving) return
  formError.value = ''
  try {
    let settings: unknown
    try { settings = JSON.parse(form.settings) } catch { throw Error('规则参数不是有效 JSON，请检查引号、逗号和括号。') }
    if (!settings || Array.isArray(settings) || typeof settings !== 'object') throw Error('规则参数必须是 JSON 对象。')
    if (!/^[a-z][a-z0-9-]{0,63}$/.test(form.id.trim())) throw Error('方案标识须以小写字母开头，仅含小写字母、数字和短横线，最多 64 字符。')
    if (!form.name.trim()) throw Error('请填写方案名称。')
    const plugins = ['docx-package', ...new Set(form.plugins.filter(id => id !== 'docx-package'))]
    if (!props.source) throw Error('请先选择来源方案。')
    emit('save', profileCopy(props.source, { id: form.id.trim(), name: form.name.trim(), description: form.description.trim(), plugins, settings: settings as Record<string, unknown> }))
  } catch (error) { formError.value = error instanceof Error ? error.message : String(error) }
}
</script>
<template>
  <dialog ref="dialog" class="dialog profile-dialog" aria-modal="true" aria-labelledby="profile-dialog-title" @keydown="trapFocus" @cancel.prevent="close" @click="($event.target === dialog) && close()">
    <form @submit.prevent="save" :aria-busy="saving">
      <div class="dialog-heading"><div><span class="dialog-symbol" aria-hidden="true"><AppIcon name="copy" /></span><h2 id="profile-dialog-title">{{ importing ? '导入为新方案' : '复制为新方案' }}</h2></div><button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="close"><AppIcon name="close" /></button></div>
      <div class="profile-dialog-body">
      <p v-if="source?.school" class="field-help">来源方案：{{ profileLabel(source) }}</p>
      <p v-else-if="source?.scoped_rules?.length" class="field-help">此方案含分范围规则，可修改名称和说明；规则调整请编辑完整方案 JSON 后重新导入。</p>
      <p v-if="fieldsError" class="notice warm-notice" role="alert">常用规则表单暂不可用，可展开高级参数编辑或关闭后重试。</p>
      <p v-if="becomesCustom" class="notice warm-notice" role="status">规则已更改，将保存为独立自定义方案。学校要求请在依据包中重新确认。</p>
      <fieldset class="dialog-fields" :disabled="saving">
        <div class="form-group"><label for="profile-name">方案名称</label><input id="profile-name" ref="nameInput" v-model="form.name" required maxlength="120"/></div>
        <div class="form-group"><label for="profile-desc">适用范围</label><textarea id="profile-desc" v-model="form.description" rows="2" maxlength="2000"/></div>
        <RuleFields v-if="genericEnabled && fields?.length" v-model="form.settings" :fields="fields" :disabled="saving" />
        <section v-if="academicEnabled && academicFields?.fields.length" class="academic-fields" aria-labelledby="academic-fields-title">
          <h3 id="academic-fields-title">标题与段落排版</h3>
          <RuleFields v-model="form.settings" :fields="academicFields.fields" :disabled="saving" collapsible />
        </section>
        <section v-if="structureEnabled && structureFields?.fields.length" class="academic-fields" aria-labelledby="structure-fields-title">
          <h3 id="structure-fields-title">章节、题注与页码</h3>
          <RuleFields v-model="form.settings" :fields="structureFields.fields" :disabled="saving" collapsible />
        </section>
        <DocumentFieldRules v-if="form.plugins.includes('document-fields') && documentFields" v-model="form.settings" :metadata="documentFields" :disabled="saving" />
        <details class="profile-advanced"><summary>高级参数与插件</summary>
          <div class="form-group"><label for="profile-id">方案标识</label><input id="profile-id" v-model="form.id" required pattern="[a-z][a-z0-9-]{0,63}" maxlength="64" aria-describedby="profile-id-help"/><p id="profile-id-help" class="field-help">已自动生成；仅需自定义标识时修改。</p></div>
          <fieldset class="plugin-fieldset"><legend>启用插件</legend><label v-for="plugin in availablePlugins" :key="plugin.id"><input v-model="form.plugins" type="checkbox" :value="plugin.id" :disabled="plugin.id === 'docx-package'"/> {{ engineLabel(plugin.id, plugin.name) }}<small v-if="plugin.available === false" class="field-help">{{ plugin.reason ? '不可用：' + plugin.reason : '不可用' }}；执行前需补齐环境。</small></label></fieldset>
          <div class="form-group"><label for="profile-settings">规则参数（JSON）</label><textarea id="profile-settings" v-model="form.settings" rows="8" class="code-input" spellcheck="false"/></div>
        </details>
        <details v-if="changes.length" class="profile-advanced"><summary>相对来源方案修改了 {{ changes.length }} 项</summary><ul class="profile-changes"><li v-for="change in changes" :key="change.path"><strong>{{ editableFields.find(field => field.path === change.path)?.label || automaticTargets.find(([path]) => path === change.path)?.[1] || (change.path === 'plugins' ? '检测能力' : '高级规则参数') }}</strong><del>{{ changeValue(change.path, change.previous) }}</del><span>→ {{ changeValue(change.path, change.next) }}</span></li></ul></details>
        <p v-else class="field-help">规则与来源方案一致。</p>
      </fieldset>
      </div>
      <div class="profile-dialog-footer"><p v-if="formError || saveError" class="notice error-notice" role="alert">{{ formError || saveError }}</p><div class="dialog-actions"><button type="button" class="button secondary" :disabled="saving" @click="close">取消</button><button type="submit" class="button primary" :disabled="saving">{{ saving ? '正在保存…' : '保存方案' }}</button></div></div>
    </form>
  </dialog>
</template>

<style scoped>
.profile-dialog { width: min(880px, calc(100% - 32px)); max-height: calc(100dvh - 48px); padding: 0; border-radius: 14px; overflow: hidden; }
.profile-dialog > form { display: flex; flex-direction: column; max-height: calc(100dvh - 48px); min-height: 0; }
.dialog-heading { align-items: center; padding: 20px 24px; margin: 0; border-bottom: 1px solid var(--line); flex: none; }
.dialog-heading > div { display: flex; align-items: center; gap: 12px; min-width: 0; }
.dialog-heading h2 { font-size: 21px; }
.dialog-symbol { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 9px; background: var(--brand-soft); color: var(--brand); flex: none; }
.dialog-symbol :deep(svg) { width: 19px; height: 19px; }
.academic-fields { margin-top: 20px; }
.academic-fields h3 { font-size: 16px; }
.profile-dialog-body { overflow-y: auto; padding: 24px; min-height: 0; overscroll-behavior: contain; }
.profile-dialog-body > .dialog-fields > .form-group:nth-child(-n+2) { margin-bottom: 20px; }
.profile-dialog-body :deep(.rule-fieldset) { margin-top: 20px; padding-top: 18px; }
.profile-dialog-footer { flex: none; padding: 16px 24px; background: var(--surface-soft); border-top: 1px solid var(--line); }
.profile-dialog-footer .dialog-actions { margin: 0; }
.profile-dialog-footer .notice { margin-block: 0 14px; }
.profile-advanced { margin-top: 16px; border-top: 1px solid var(--line); }
summary { min-height: 44px; padding-block: 12px; font-size: 15px; font-weight: 600; cursor: pointer; }
summary:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
.profile-changes { padding-left: 20px; margin: 0; }
.profile-changes li { padding-block: 8px; overflow-wrap: anywhere; font-size: 14px; }
.profile-changes strong, .profile-changes del, .profile-changes span { display: block; }
.profile-changes del { color: var(--muted); }
@media (max-width: 600px) { .profile-dialog { width: calc(100% - 24px); max-width: calc(100% - 24px); max-height: calc(100dvh - 24px); border-radius: 12px; } .profile-dialog > form { max-height: calc(100dvh - 24px); } .dialog-heading, .profile-dialog-body, .profile-dialog-footer { padding: 18px; } .dialog-heading h2 { font-size: 19px; } .dialog-symbol { display: none; } .profile-dialog-footer .button { flex: 1; } }
</style>


