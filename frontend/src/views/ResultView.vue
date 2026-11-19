<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Artifact, Job } from '../types'
import type { ReviewDraftCache } from '../utils/reportWorkspace'
import ArtifactList from '../components/ArtifactList.vue'
import ReportContent from '../components/ReportContent.vue'
import RepairPanel from '../components/RepairPanel.vue'
import ReportWorkspace from '../components/ReportWorkspace.vue'
import OcrEvidenceDialog from '../components/OcrEvidenceDialog.vue'
import JobProgress from '../components/JobProgress.vue'
import AppIcon from '../components/AppIcon.vue'
import { supportsRepairFormat } from '../composables/useDocumentRepair'
import { displayEvidence } from '../utils/report'
import { kindLabel, profileLabel } from '../utils/materials'
import { formatDateTime } from '../utils/date'
const props = defineProps<{ job: Job|null; artifacts: Artifact[]; error?: string; loading?: boolean; retrying?: boolean; artifactsLoading?: boolean; reviewDraftCache?: ReviewDraftCache }>()
const emit = defineEmits<{ back: []; reload: []; retry: []; loadArtifacts: []; newDraft: []; repaired: [Job] }>()
const repairing = ref(false)
const workspace = ref<InstanceType<typeof ReportWorkspace>>()
const ocrDialog = ref<InstanceType<typeof OcrEvidenceDialog>>()
const profileName = computed(() => {
  const snapshot = props.job?.result?.profile_snapshot
  return snapshot ? profileLabel(snapshot) : '检测方案名称未记录'
})
</script>
<template>
  <div class="page">
    <button type="button" class="text-button back-button" @click="emit('back')"><AppIcon name="chevron-right" class="back-icon" />返回检测记录</button>
    <div class="page-heading result-heading"><div class="result-document"><span class="result-document-icon" aria-hidden="true"><AppIcon name="file" /></span><div><h1 :title="job?.filename || '检测结果'">{{ job?.filename || '检测结果' }}</h1><p class="result-metadata"><span>{{ profileName }}</span><span>{{ kindLabel(job?.kind) }}</span><time v-if="job?.created_at" :datetime="job.created_at">{{ formatDateTime(job.created_at) }}</time><span v-else>时间未记录</span></p></div></div><div class="result-actions"><button class="button secondary" type="button" title="使用本次检测保存的文档与方案" :disabled="!job || retrying || repairing || job?.status==='queued'||job?.status==='running'" @click="emit('retry')"><AppIcon name="refresh" />{{ retrying ? '正在创建任务…' : '重试本次检测' }}</button><button class="button primary" type="button" :disabled="!job || retrying || repairing || job.status === 'queued' || job.status === 'running'" @click="emit('newDraft')">检测修改稿<AppIcon name="arrow-right" /></button></div></div>
    <div v-if="error" class="notice error-notice" role="alert">{{ error }} <button class="text-button" type="button" :disabled="loading" @click="emit('reload')">重新读取结果</button></div>
    <p v-else-if="!job" class="empty-state" role="status">{{ loading ? '正在读取检测结果…' : '未找到此检测任务。' }}</p>
    <JobProgress v-if="job && (job.status==='queued'||job.status==='running')" :job="job" @updated="emit('reload')" />
    <p v-if="job?.error" class="notice error-notice" role="alert">{{ displayEvidence(job.error) }}</p>
    <p v-if="job?.repair" class="field-help"><a :href="`#job/${job.repair.source_job_id}`">查看原检测</a></p>
    <ReportContent v-if="job?.result" :key="job.id" :result="job.result" :can-locate-ocr="job.status === 'completed' && job.result.status !== 'incomplete' && job.result.input_format === 'pdf'" @locate-ocr="ocrDialog?.open($event)">
      <template #issue-actions="{ index }"><button type="button" class="text-button" :disabled="job.status !== 'completed' || job.result?.status === 'incomplete'" @click="workspace?.open(index)">查看原稿与依据 / 复核</button></template>
      <template #repair>
        <template v-if="job.status !== 'queued' && job.status !== 'running'">
          <RepairPanel v-if="supportsRepairFormat(job)" :key="`repair-${job.id}`" :job="job" :disabled="retrying" @busy="repairing = $event" @repaired="emit('repaired', $event)" />
          <section v-else class="panel format-repair-help">
            <div class="panel-heading"><h2>针对性修复</h2></div>
            <p class="field-help">自动修复仅支持 DOCX。请根据问题与证据修改原稿，再上传修改稿复检。</p>
          </section>
        </template>
      </template>
      <template #details>
        <ReportWorkspace ref="workspace" :key="`workspace-${job.id}`" :job="job" :draft-cache="reviewDraftCache" />
        <section class="panel artifact-panel"><div class="panel-heading"><h2>报告与附件</h2><button type="button" class="text-button" :disabled="artifactsLoading" @click="emit('loadArtifacts')">{{ artifactsLoading ? '正在读取…' : '刷新附件' }}</button></div><ArtifactList :items="artifacts" :loading="artifactsLoading"/></section>
      </template>
    </ReportContent>
    <OcrEvidenceDialog v-if="job?.result?.input_format === 'pdf'" ref="ocrDialog" :key="`ocr-${job.id}`" :job="job" />
    <section v-if="job && !job.result" class="panel artifact-panel"><div class="panel-heading"><h2>任务附件</h2><button type="button" class="text-button" :disabled="artifactsLoading" @click="emit('loadArtifacts')">{{ artifactsLoading ? '正在读取…' : '刷新附件' }}</button></div><ArtifactList :items="artifacts" :loading="artifactsLoading"/></section>
    <p v-if="job?.status === 'cancelled'" class="notice neutral-notice" role="status">检测已取消，未生成完整结论。可重新检测此文档。</p>
    <p v-else-if="!job?.result && job && job.status!=='queued' && job.status!=='running'" class="notice neutral-notice">未生成结果，请重试或检查运行环境。</p>
  </div>
</template>

<style scoped>
.back-button { display: inline-flex; align-items: center; gap: 4px; margin-bottom: 16px; color: var(--muted); font-size: 14px; }
.back-icon { transform: rotate(180deg); }
.result-heading { gap: 20px 24px; align-items: center; margin-bottom: 28px; }
.result-document { display: flex; align-items: flex-start; gap: 16px; flex: 1 1 340px; min-width: 0; }
.result-document > div { min-width: 0; }
.result-document-icon { display: grid; place-items: center; width: 48px; height: 56px; flex-shrink: 0; margin-top: 3px; border: 1px solid var(--line); border-radius: 10px; color: var(--brand); background: var(--surface); }
.result-document-icon svg { width: 24px; height: 24px; }
.result-heading h1 { margin-bottom: 12px; }
.result-metadata { display: flex; flex-wrap: wrap; gap: 6px 0; font-size: 14px; line-height: 1.5; }
.result-metadata > * { min-width: 0; padding-right: 12px; overflow-wrap: anywhere; }
.result-metadata > * + * { padding-left: 12px; border-left: 1px solid var(--line-strong); }
.result-actions { gap: 8px; }
.result-actions .button { font-size: 14px; }
.format-repair-help {
  margin-bottom: 20px;
  padding: var(--panel-padding, 22px);
}

.format-repair-help p {
  margin-bottom: 0;
}
@container workspace (max-width: 640px) { .result-document-icon { display: none; } .result-document { gap: 0; } .result-actions .button { padding-inline: 10px; } }
@media (max-width: 640px) { .result-document-icon { display: none; } .result-document { gap: 0; } .result-actions .button { padding-inline: 10px; } }
</style>

