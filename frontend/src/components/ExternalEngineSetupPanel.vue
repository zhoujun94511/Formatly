<script setup lang="ts">
import { computed } from 'vue'
import type { ExternalEngineStatus } from '../types'
import { useExternalEngineSetup } from '../composables/useExternalEngineSetup'
import { auditRoute } from '../utils/auditRoute'
import AppIcon from './AppIcon.vue'
import StatusBadge from './StatusBadge.vue'
import ProfileSummary from './ProfileSummary.vue'

const props = defineProps<{ engine: ExternalEngineStatus; loading?: boolean }>()
const emit = defineEmits<{ refresh: [] }>()
const engine = computed(() => props.engine), refreshing = computed(() => !!props.loading)
const { kind, preflight, checking, error, canCheck, ready, check } = useExternalEngineSetup(engine, refreshing)
const stageLabels: Record<ExternalEngineStatus['stage'], string> = {
  missing: '未接入', files: '目录不完整', python: 'Python 不可用', dependencies: '依赖不完整', rules: '规则校验未通过', ready: '已接入', error: '检查失败',
}
const discoveryLabels: Record<ExternalEngineStatus['discovery'], string> = { default: '同级目录自动发现', environment: '环境变量', configuration: '本机保存的配置' }
const checkLabels = { ok: '已通过', error: '未通过', pending: '待检查' }
const failedChecks = computed(() => props.engine.checks.filter(item => item.status === 'error'))
const checkCommand = "python -m formatly engines check --root 'C:\\Tools\\school-engine' --python 'C:\\Tools\\school-engine\\.venv\\Scripts\\python.exe'"
const configureCommand = "python -m formatly engines configure --root 'C:\\Tools\\school-engine' --python 'C:\\Tools\\school-engine\\.venv\\Scripts\\python.exe'"
</script>

<template>
  <section id="external-engine-setup" class="panel external-engine-panel" aria-labelledby="external-engine-title" :aria-busy="refreshing">
    <div class="engine-heading">
      <div><h2 id="external-engine-title">外部专项引擎</h2><p>用于已有专项规则的 DOCX 论文和实习报告检测。</p></div>
      <StatusBadge :status="engine.available ? 'available' : 'unavailable'" :label="loading ? '正在检查…' : stageLabels[engine.stage]" />
    </div>
    <p class="engine-source">配置来源：{{ discoveryLabels[engine.discovery] }}</p>
    <p v-if="engine.discovery === 'environment'" class="notice warm-notice">环境变量优先于保存的配置。更换引擎前，请在服务主机更新或清除 FORMATLY_LEGACY_ROOT 和 FORMATLY_LEGACY_PYTHON，再重启服务。</p>
    <div v-if="!loading && failedChecks.length" class="engine-problems" role="status" aria-live="polite">
      <p v-for="item in failedChecks" :key="item.id"><strong>{{ item.label }}：</strong>{{ item.message }}</p>
    </div>
    <details v-if="engine.checks.length" class="engine-details">
      <summary>查看接入检查明细</summary>
      <ul class="engine-checks" aria-label="接入检查明细">
        <li v-for="item in engine.checks" :key="item.id">
          <div class="engine-check-heading"><strong>{{ item.label }}</strong><StatusBadge :status="item.status === 'pending' ? 'not_checked' : item.status" :label="checkLabels[item.status]" /></div>
          <p>{{ item.message }}</p>
        </li>
      </ul>
    </details>
    <ol class="engine-steps">
      <li>
        <h3>准备兼容引擎</h3>
        <p>使用可信来源的完整引擎包，保留其同级 vendor 目录及来源原件。</p>
        <details class="engine-details">
          <summary>查看目录要求</summary>
          <p>该入口使用固定的专项引擎契约；不能直接连接任意转换工具或在线服务。</p>
          <ul class="engine-files"><li v-for="file in engine.required_files" :key="file.path"><code>{{ file.path }}</code><span>{{ file.present ? '已找到' : '缺少' }}</span></li></ul>
          <p>引擎会核验规则配置、来源文件与供应组件。请保留原目录结构。</p>
        </details>
      </li>
      <li>
        <h3>在服务主机配置并重启</h3>
        <p>在运行 Formatly 的电脑上执行配置命令，通过校验后保存，再重启当前服务。</p>
        <details class="engine-details">
          <summary>查看 PowerShell 配置命令</summary>
          <p>将示例路径替换为实际引擎目录和 Python 解释器路径，并使用启动 Formatly 时相同的数据目录。</p>
          <h4>检查并保存</h4>
          <pre tabindex="0" role="region" aria-label="专项引擎检查与配置命令"><code>{{ checkCommand }}
{{ configureCommand }}</code></pre>
          <h4>检查当前配置 / 恢复自动发现</h4>
          <pre tabindex="0" role="region" aria-label="专项引擎维护命令"><code>python -m formatly engines check
python -m formatly engines clear
python -m formatly engines --help</code></pre>
          <p>设置了 FORMATLY_LEGACY_ROOT / FORMATLY_LEGACY_PYTHON 时，环境变量覆盖保存的配置。清除配置不会清除环境变量。</p>
        </details>
        <button class="button secondary" type="button" :disabled="refreshing" @click="emit('refresh')"><AppIcon name="refresh" />{{ loading ? '正在检查…' : '重新检查接入' }}</button>
      </li>
      <li>
        <h3>验证方案并检测原稿</h3>
        <div class="engine-validation">
          <label class="form-group" for="external-engine-kind">文档类型<select id="external-engine-kind" v-model="kind" :disabled="refreshing"><option value="thesis">毕业论文</option><option value="intern">实习报告</option></select></label>
          <button class="button secondary" type="button" :disabled="!canCheck || checking" @click="check">{{ checking ? '正在验证…' : '验证方案' }}</button>
          <a v-if="ready" class="button primary" :href="`#${auditRoute(engine.profile_id, kind)}`">使用此方案检测<AppIcon name="arrow-right" /></a>
          <button v-else class="button primary" type="button" disabled>使用此方案检测<AppIcon name="arrow-right" /></button>
        </div>
        <p v-if="error" class="notice error-notice" role="alert">{{ error }}</p>
        <div v-else class="engine-validation-status" role="status" aria-live="polite">
          <p v-if="checking">正在检查所选文档类型的专项方案…</p>
          <p v-else-if="ready">方案验证通过，可上传 DOCX 原稿。</p>
          <template v-else-if="preflight"><p>方案暂不可用。</p><p v-for="plugin in preflight.plugins.filter(item => !item.available)" :key="plugin.id">{{ plugin.reason || '检测能力不可用，请重新检查接入。' }}</p></template>
          <p v-else>{{ engine.available ? '选择文档类型后验证方案。' : '完成接入检查后可验证方案。' }}</p>
        </div>
        <ProfileSummary v-if="preflight?.summary" :summary="preflight.summary" />
        <p v-for="warning in preflight?.warnings || []" :key="warning" class="notice warm-notice">{{ warning }}</p>
      </li>
    </ol>
    <p class="engine-alternative">按学校模板检测？在<a href="#new?source=school">新建检测</a>页直接上传模板，或<a href="#profiles">选择已保存方案</a>。</p>
  </section>
</template>

<style scoped>
.external-engine-panel { min-width: 0; padding: var(--panel-padding); }
.engine-heading { display: flex; justify-content: space-between; align-items: start; flex-wrap: wrap; gap: 12px 20px; }
.engine-heading h2 { font-size: 20px; line-height: 1.5; }
.engine-heading p, .engine-source, .engine-steps p, .engine-alternative { margin: 6px 0 0; color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }
.engine-source { margin-block: 12px; }
.engine-problems { border-left: 3px solid var(--warning); padding-left: 12px; color: var(--warning); margin-block: 16px; overflow-wrap: anywhere; }
.engine-problems p { margin: 4px 0; font-size: 14px; }
.engine-steps { margin: 20px 0; padding-left: 24px; display: grid; gap: 24px; }
.engine-steps > li { min-width: 0; padding-left: 4px; }
.engine-steps > li::marker { color: var(--brand); font-weight: 700; }
.engine-steps h3 { margin: 0; font-size: 16px; line-height: 1.6; }
.engine-details { margin-block: 6px 12px; font-size: 14px; min-width: 0; }
.engine-details summary { width: fit-content; min-height: 44px; padding-block: 11px; cursor: pointer; color: var(--brand); }
.engine-details h4 { margin: 16px 0 8px; font-size: 14px; }
.engine-checks { list-style: none; padding: 0; margin: 4px 0 12px; }
.engine-checks > li { padding-block: 12px; border-bottom: 1px solid var(--line); min-width: 0; }
.engine-checks > li:last-child { border-bottom: 0; }
.engine-check-heading { display: flex; align-items: start; justify-content: space-between; flex-wrap: wrap; gap: 8px 16px; }
.engine-check-heading strong, .engine-checks p { overflow-wrap: anywhere; }
.engine-checks p { color: var(--muted); margin: 6px 0 0; }
.engine-details pre { max-width: 100%; margin: 8px 0; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-soft); color: var(--ink); white-space: pre-wrap; overflow-wrap: anywhere; font-size: 13px; line-height: 1.7; }
.engine-files { list-style: none; padding: 0; margin: 12px 0; }
.engine-files li { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 16px; padding-block: 6px; }
.engine-files code { min-width: 0; overflow-wrap: anywhere; }
.engine-files span { color: var(--muted); }
.engine-validation { display: flex; align-items: end; flex-wrap: wrap; gap: 12px; margin-top: 12px; }
.engine-validation label { display: grid; gap: 8px; margin: 0; min-width: min(100%, 180px); font-size: 15px; font-weight: 600; }
.engine-validation select { width: 100%; }
.engine-validation-status { min-height: 26px; margin-top: 10px; }
.engine-alternative { padding-top: 16px; border-top: 1px solid var(--line); }
.engine-alternative a { margin-inline: 4px; }
.engine-details summary:focus-visible, .engine-details pre:focus-visible { outline: 3px solid var(--brand); outline-offset: 3px; }
@container workspace (max-width: 560px) { .engine-validation { display: grid; grid-template-columns: minmax(0, 1fr); } .engine-validation .button { width: 100%; } }
@media (max-width: 480px) { .engine-validation { display: grid; grid-template-columns: minmax(0, 1fr); } .engine-validation .button { width: 100%; } }
</style>
