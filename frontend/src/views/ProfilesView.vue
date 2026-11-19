<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { DocumentKind, Plugin, Profile } from '../types'
import ProfileDialog from '../components/ProfileDialog.vue'
import { documentKinds, isHiddenPreset, kindLabel, profileLabel } from '../utils/materials'
import { engineLabel } from '../utils/report'
import { parseImportedProfile } from '../utils/profileFields'
import { useProfileFields } from '../composables/useProfileFields'
import { useProfileTrial } from '../composables/useProfileTrial'
import { usePagedItems } from '../composables/usePagedItems'
import ListPagination from '../components/ListPagination.vue'
import AppIcon from '../components/AppIcon.vue'

const props = defineProps<{ profiles: Profile[]; plugins: Plugin[]; saving?: boolean; saveError?: string; saveVersion?: number }>()
const emit = defineEmits<{ save: [Omit<Profile, 'id'> & { id: string }]; clearError: []; useProfile: [Profile]; openJob: [string] }>()
const trial = useProfileTrial()
async function runTrial(profile: Profile) { const id = await trial.run(profile); if (id) emit('openJob', id) }
const source = ref<Profile | null>(null)
const importing = ref(false), importError = ref('')
const importInput = ref<HTMLInputElement>()
const fields = useProfileFields()
const query = ref(''), filterKind = ref('')
const filteredProfiles = computed(() => props.profiles.filter(profile => {
  const text = query.value.trim().toLocaleLowerCase()
  return (!text || `${profileLabel(profile)} ${profile.description || ''}`.toLocaleLowerCase().includes(text))
    && !isHiddenPreset(profile)
    && (!filterKind.value || !profile.kinds?.length || profile.kinds.includes(filterKind.value as DocumentKind))
}))
const { page, displayed, setPage } = usePagedItems(filteredProfiles)
let importRevision = 0, disposed = false
onBeforeUnmount(() => { disposed = true; importRevision += 1 })
const opener = ref<HTMLButtonElement | null>(null)
function open(profile: Profile, event: Event) { importRevision += 1; emit('clearError'); importing.value = false; opener.value = event.currentTarget as HTMLButtonElement; source.value = profile }
function close() { importRevision += 1; source.value = null; void nextTick(() => opener.value?.focus()) }
async function importProfile(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]
  input.value = ''; importError.value = ''
  if (!file || props.saving) return
  const request = ++importRevision
  try {
    if (file.size > 2 * 1024 * 1024) throw Error('方案 JSON 不能超过 2 MB。')
    const profile = parseImportedProfile(await file.text())
    if (disposed || request !== importRevision) return
    emit('clearError'); importing.value = true; source.value = profile
  } catch (value) { if (!disposed && request === importRevision) importError.value = value instanceof Error ? value.message : String(value) }
}
function exportProfile(profile: Profile) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(profile, null, 2) + '\n'], { type: 'application/json' }))
  const link = document.createElement('a'); link.href = url; link.download = `${profile.id}.json`; link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
watch(() => props.saveVersion, () => close())
</script>
<template>
  <div class="page profiles-page">
    <div class="page-heading"><div><h1>规则方案</h1><p>保存不同学校与材料的格式要求，检测时直接选用。</p></div><button class="button secondary" type="button" :disabled="saving" @click="opener = $event.currentTarget as HTMLButtonElement; importInput?.click()"><AppIcon name="upload" />导入方案 JSON</button><input ref="importInput" class="visually-hidden" type="file" accept=".json,application/json" aria-label="导入规则方案 JSON" tabindex="-1" :disabled="saving" @change="importProfile" /></div>
    <p v-if="importError" class="notice error-notice" role="alert">{{ importError }}</p>
    <p v-if="trial.error.value" class="notice error-notice" role="alert">{{ trial.error.value }}</p>
    <p v-if="fields.error.value" class="notice warm-notice" role="alert">常用规则表单读取失败：{{ fields.error.value }} <button class="text-button" type="button" @click="fields.load">重新读取</button></p>
    <section class="profile-browser" aria-label="选择规则方案">
      <div class="table-toolbar profile-toolbar">
        <label class="search-field"><AppIcon name="search" /><span class="visually-hidden">搜索规则方案</span><input v-model="query" type="search" placeholder="搜索方案名称" /></label>
        <label class="inline-label" for="profile-kind-filter"><span>适用材料</span><select id="profile-kind-filter" v-model="filterKind"><option value="">全部材料</option><option v-for="kind in documentKinds" :key="kind.value" :value="kind.value">{{ kind.label }}</option></select></label>
        <span class="profile-count" role="status">{{ filteredProfiles.length }} 个方案</span>
      </div>
    <div class="cards-grid profiles-grid">
      <article v-for="profile in displayed" :key="profile.id" class="panel profile-card">
        <div class="card-title-row"><span class="profile-symbol" aria-hidden="true"><AppIcon name="layers" /></span><div><h2>{{ profileLabel(profile) }}</h2></div></div>
        <div class="tag-list profile-kinds"><span v-for="kind in profile.kinds" :key="kind" class="tag">{{ kindLabel(kind) }}</span><span v-if="!profile.kinds?.length" class="tag">全部材料</span><span v-if="profile.school" class="school-tag">学校要求</span></div>
        <div v-if="profile.plugins?.includes('legacy-school')" class="notice warm-notice">此方案依赖可选外部专项引擎；未安装时可改用「学校要求」生成方案或预置方案。</div>
        <details class="profile-details"><summary>方案详情与更多操作</summary><p v-if="profile.description" class="card-description">{{ profile.description }}</p><span class="card-id">{{ profile.id }}</span><div class="tag-list"><span v-for="plugin in profile.plugins" :key="plugin" class="tag">{{ engineLabel(plugin, plugins.find(item => item.id === plugin)?.name) }}</span></div><div class="profile-more-actions"><button class="text-button" type="button" :disabled="!!trial.busyId.value || saving" @click="runTrial(profile)">{{ trial.busyId.value === profile.id ? '正在提交样例…' : '匿名样例试跑' }}</button><button type="button" class="text-button" @click="exportProfile(profile)"><AppIcon name="download" />导出 JSON</button></div></details>
        <div class="profile-actions"><button type="button" class="button secondary" :disabled="saving" @click="open(profile, $event)"><AppIcon name="copy" />复制方案</button><button class="button primary" type="button" :disabled="saving" @click="emit('useProfile', profile)">使用此方案<AppIcon name="arrow-right" /></button></div>
      </article>
    </div>
    <div v-if="!filteredProfiles.length" class="panel empty-state"><AppIcon name="layers" /><h2>{{ profiles.length ? '没有匹配的方案' : '暂无规则方案' }}</h2><p>{{ profiles.length ? '调整搜索内容或材料筛选后重试。' : '可从学校要求生成方案，或导入已有方案 JSON。' }}</p><button v-if="query || filterKind" class="button secondary" type="button" @click="query = ''; filterKind = ''">清除筛选</button></div>
    <ListPagination :page="page" :total="filteredProfiles.length" label="规则方案分页" @change="setPage" />
    </section>
    <ProfileDialog :open="!!source" :source="source" :plugins="plugins" :fields="fields.metadata.value?.fields" :academic-fields="fields.metadata.value?.academic_fields" :structure-fields="fields.metadata.value?.structure_fields" :document-fields="fields.metadata.value?.document_fields" :fields-error="fields.error.value" :importing="importing" :saving="saving" :save-error="saveError" @close="close" @save="emit('save', $event)" />
  </div>
</template>

<style scoped>
.profile-toolbar { margin-bottom: 20px; padding: 0; gap: 12px 20px; }
.profile-toolbar .search-field { --search-basis: 260px; max-width: 400px; }
.profile-count { margin-left: auto; color: var(--muted); font-size: 14px; white-space: nowrap; }
.profiles-grid { grid-template-columns: repeat(auto-fit, minmax(min(100%, 350px), 1fr)); gap: 20px; }
.profile-card { display: flex; flex-direction: column; gap: 18px; padding: 24px; }
.profile-card .card-title-row { gap: 12px; align-items: flex-start; }
.profile-card h2 { font-size: 19px; line-height: 1.5; }
.profile-symbol { display: grid; place-items: center; flex: none; width: 40px; height: 40px; background: var(--brand-soft); color: var(--brand); border: 1px solid var(--info-line); border-radius: 10px; }
.profile-symbol :deep(svg) { width: 21px; height: 21px; }
.profile-kinds { margin: 0; gap: 6px; }
.school-tag { font-size: 12px; padding: 3px 8px; border-radius: 5px; color: var(--success); background: var(--success-bg); }
.profile-details { margin: 0; padding-top: 0; flex: 1; }
.profile-details > summary { color: var(--muted); font-weight: 500; }
.profile-details .card-description { margin-top: 8px; }
.profile-more-actions { display: flex; flex-wrap: wrap; gap: 8px 16px; padding-top: 12px; }
.profile-more-actions .text-button { display: inline-flex; align-items: center; gap: 6px; }
.profile-more-actions :deep(svg) { width: 16px; height: 16px; }
.profile-actions { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin: 0; padding-top: 16px; border-top: 1px solid var(--line); }
.profile-actions .button { flex: 1 1 auto; }
.empty-state { padding: 42px 24px; }
.empty-state > :deep(svg) { width: 32px; height: 32px; color: var(--muted); margin-bottom: 12px; }
.empty-state h2 { font-size: 19px; }
.empty-state p { margin: 8px 0 20px; }
@container workspace (max-width: 640px) { .profile-toolbar .search-field { max-width: none; flex: auto; } .profile-count { margin-left: 0; } .profile-card { padding: 20px; } }
@media (max-width: 480px) { .profile-toolbar .search-field { max-width: none; } .profile-card { padding: 20px; } }
</style>
