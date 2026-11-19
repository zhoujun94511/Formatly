import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '../..')
const localPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const python = process.env.FORMATLY_TEST_PYTHON || (existsSync(localPython) ? localPython : 'python')

test('批量预检失败可保留原稿并通过明确入口重试', async ({ page }) => {
  let checks = 0
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route(/\/api\/profiles\/generic\/preflight\?/, async route => {
    checks++
    if (checks === 1) await route.fulfill({ status: 503, json: { error: '临时预检失败，请重试。' } })
    else await route.continue()
  })
  await page.goto('/#batch')
  await page.getByRole('combobox', { name: '规则方案', exact: true }).selectOption('generic')
  await page.locator('input[type=file]').setInputFiles({
    name: '匿名批量恢复.md', mimeType: 'text/markdown', buffer: Buffer.from('# 摘要\n匿名批量预检恢复样例。\n'),
  })
  const submit = page.getByRole('button', { name: /^开始检测/ })
  await expect(page.getByRole('alert')).toContainText('临时预检失败')
  await expect(submit).toBeDisabled()
  await page.getByRole('button', { name: '重新核对方案', exact: true }).click()
  await expect(submit).toBeEnabled()
  expect(checks).toBe(2)
  await expect(page.getByRole('list', { name: '已选原稿' })).toContainText('匿名批量恢复.md')
  await submit.click()
  await expect(page).toHaveURL(/#batch\/[a-f0-9]{32}$/)
  await expect(page.getByRole('heading', { name: '本批结果', exact: true })).toBeVisible()
  await expect(page.locator('.batch-results > li')).toHaveCount(1)
  expect(errors).toEqual([])
})

test('批量发送后预览到期且回执断网仍以原批次恢复', async ({ page, request }) => {
  const profileId = 'batch-expiry-recovery-ui'
  const saved = await request.post('/api/profiles', { data: {
    id: profileId, name: '匿名批次恢复验收', plugins: ['docx-package', 'generic-format'],
    settings: { body: { size_pt: 12, style_ids: ['Normal'] } }, kinds: ['thesis'],
  } })
  expect(saved.status()).toBe(201)
  const manuscript = execFileSync(python, ['-B', '-c',
    "import sys; sys.path.insert(0, 'tests'); from test_generic_scope_workflow import anonymous_manuscript; sys.stdout.buffer.write(anonymous_manuscript())"], { cwd: root })
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.clock.install()
  await page.route('**/api/document-previews', async route => {
    const response = await route.fetch()
    const preview = await response.json()
    preview.expires_at = new Date(Date.now() + 60_000).toISOString()
    await route.fulfill({ response, json: preview })
  })
  let release = () => {}
  const blocked = new Promise<void>(resolve => { release = resolve })
  const receipts: { batch_id: string; items: { job_id?: string }[] }[] = []
  const payloads: string[] = []
  await page.route('**/api/batches', async route => {
    payloads.push(route.request().postData() || '')
    const response = await route.fetch()
    expect(response.status()).toBe(202)
    receipts.push(await response.json())
    if (receipts.length === 1) {
      await blocked
      await route.abort('connectionreset').catch(() => {})
    } else await route.fulfill({ response })
  })
  try {
    await page.goto('/#batch')
    await page.getByRole('combobox', { name: '规则方案', exact: true }).selectOption(profileId)
    await page.locator('input[type=file]').setInputFiles({ name: '匿名过期恢复.docx',
      mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: manuscript })
    const scope = page.getByRole('region', { name: '原稿范围匹配' })
    await scope.getByRole('button', { name: '读取原稿范围', exact: true }).click()
    await expect(scope.getByText(/已处理 0\/1 条/)).toBeVisible()
    await scope.getByRole('button', { name: '暂不匹配', exact: true }).click()
    await expect(scope.getByText(/已处理 1\/1 条，可以开始检测/)).toBeVisible()
    const submit = page.getByRole('button', { name: /^开始检测/ })
    await expect(submit).toBeEnabled()
    await submit.click()
    await expect.poll(() => receipts.length).toBe(1)
    await page.clock.fastForward(60_001)
    await expect(scope.getByRole('alert')).toContainText('原稿预览已过期')
    release()
    const recover = page.getByRole('button', { name: '重试原批次', exact: true })
    await expect(recover).toBeEnabled()
    await expect(submit).toBeDisabled()
    await recover.click()
    await expect(page).toHaveURL(new RegExp(`#batch/${receipts[0]!.batch_id}$`))
    expect(receipts).toHaveLength(2)
    expect(receipts[1]!.items.map(item => item.job_id)).toEqual(receipts[0]!.items.map(item => item.job_id))
    const field = (payload: string, name: string) => payload.match(new RegExp(`name="${name}"\\r\\n\\r\\n([^\\r]+)`))?.[1]
    expect(field(payloads[0]!, 'batch_key')).toBe(receipts[0]!.batch_id)
    expect(field(payloads[1]!, 'batch_key')).toBe(receipts[0]!.batch_id)
    expect(field(payloads[0]!, 'scope_bindings')).toBeTruthy()
    expect(field(payloads[1]!, 'scope_bindings')).toBe(field(payloads[0]!, 'scope_bindings'))
    await expect(page.locator('.batch-results > li')).toHaveCount(1)
    expect(errors).toEqual([])
  } finally { release() }
})
