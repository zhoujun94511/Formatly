import { createApp } from 'vue'
import StandaloneReport from './views/StandaloneReport.vue'
import type { Result } from './types'
import { themePlugin } from './composables/useTheme'
import './styles/tokens.css'
import './styles/components.css'
import './styles/standalone-report.css'

declare const __FORMATLY_MARK_DATA_URL__: string

function readReport(): { filename?: string; result?: Result; error?: string } {
  try {
    const raw = document.getElementById('formatly-report-data')?.textContent
    if (!raw) throw new Error('报告数据缺失，请重新导出。')
    const value: unknown = JSON.parse(raw)
    if (!value || typeof value !== 'object' || !('filename' in value) || typeof value.filename !== 'string' || !('result' in value)) {
      throw new Error('报告数据格式无效，请重新导出。')
    }
    const result = value.result
    if (!result || typeof result !== 'object' || Array.isArray(result) || !('issues' in result) || !Array.isArray(result.issues)) {
      throw new Error('报告结果格式无效，请重新导出。')
    }
    return { filename: value.filename, result: result as Result }
  } catch (error) {
    return { error: error instanceof SyntaxError ? '报告数据无法读取，请重新导出。' : error instanceof Error ? error.message : '报告无法读取，请重新导出。' }
  }
}

createApp(StandaloneReport, { ...readReport(), brandMark: __FORMATLY_MARK_DATA_URL__ }).use(themePlugin).mount('#app')
