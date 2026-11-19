<script setup lang="ts">
const props = defineProps<{ status?: string; label?: string }>()
const labels: Record<string,string> = { queued:'等待执行', running:'正在检测', completed:'检测完成', failed:'执行失败', interrupted:'已中断', cancelled:'已取消', passed:'已覆盖项通过', needs_changes:'发现格式问题', review_required:'待人工复核', incomplete:'检测未完整执行', error:'格式错误', warning:'风险提示', manual:'人工复核', ready:'环境就绪', degraded:'部分能力受限', unavailable:'不可用', available:'可用', pass:'通过', fail:'失败', ok:'正常', success:'成功', skipped:'已跳过', warn:'需留意', optional:'可选能力缺失', not_checked:'未执行', not_applicable:'已排除', unsupported:'不支持', draft:'待确认', confirmed:'已确认', needs_transcription:'待转录' }
</script><template><span class="status-badge" :class="props.status || 'unknown'">{{ props.label || labels[props.status || ''] || (props.status ? '状态未识别' : '未记录') }}</span></template>

