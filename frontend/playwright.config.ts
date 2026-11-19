import { defineConfig } from '@playwright/test'
import { existsSync } from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..')
const localPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const python = process.env.FORMATLY_TEST_PYTHON || (existsSync(localPython) ? localPython : 'python')
const port = Number(process.env.FORMATLY_TEST_PORT || 18779)
const layoutPort = Number(process.env.FORMATLY_TEST_LAYOUT_PORT || 18780)
const data = path.join(root, '.verification', `browser-${process.pid}`)
if (port === layoutPort) throw Error('Workflow and layout services require different ports')

function server(serverPort: number, directory: string) {
  return {
    command: `"${python}" -B app.py --local-only --no-browser --port ${serverPort} --data-dir "${directory}"`,
    cwd: root,
    url: `http://127.0.0.1:${serverPort}/api/health`,
    reuseExistingServer: false,
    timeout: 30_000,
    gracefulShutdown: { signal: 'SIGTERM' as const, timeout: 10_000 },
    env: { PYTHONDONTWRITEBYTECODE: '1' },
  }
}

export default defineConfig({
  testDir: './e2e',
  outputDir: '../.verification/browser-results',
  snapshotPathTemplate: '{testDir}/snapshots/{platform}/{arg}{ext}',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000, toHaveScreenshot: { animations: 'disabled', maxDiffPixelRatio: 0.002 } },
  reporter: [['list'], ['html', { outputFolder: '../.verification/browser-report', open: 'never' }]],
  use: { baseURL: `http://127.0.0.1:${port}`, browserName: 'chromium', trace: 'retain-on-failure', screenshot: 'only-on-failure', locale: 'zh-CN' },
  webServer: [server(port, data), server(layoutPort, `${data}-layout`)],
})
