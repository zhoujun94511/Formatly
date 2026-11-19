import { expect, test, type Locator, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '../..')
const localPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const python = process.env.FORMATLY_TEST_PYTHON || (existsSync(localPython) ? localPython : 'python')
const mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

function documentFixture(font?: 'SimSun') {
  const expression = font ? 'font_document("SimSun")' : 'docx_bytes()'
  return execFileSync(python, ['-B', '-c', `import sys; sys.path.insert(0, 'tests'); from test_core import docx_bytes; from test_requirement_font_scopes import font_document; sys.stdout.buffer.write(${expression})`], { cwd: root })
}

function requirementCards(page: Page, target: string) {
  return page.locator('.requirement-editor').filter({
    has: page.locator(`select[id^="requirement-target-"] option:checked[value="${target}"]`),
  })
}

async function openRequirement(card: Locator) {
  const summary = card.locator('summary')
  if (await summary.getAttribute('aria-expanded') !== 'true') await summary.click()
}

async function uploadTemplate(page: Page, name: string, buffer: Buffer) {
  await page.goto('/#schools/new')
  await page.getByLabel('学校要求名称', { exact: true }).fill(name)
  await page.locator('input[type=file]').first().setInputFiles({ name: '匿名模板.docx', mimeType: mime, buffer })
  await page.getByRole('button', { name: '上传并提取要求', exact: true }).click()
  await expect(page.getByRole('heading', { name: '已上传来源', exact: true })).toBeVisible()
}

async function publish(page: Page) {
  await page.getByRole('checkbox', { name: '已核对来源、材料类型和要求值；无法自动检查的内容已选人工复核。' }).check()
  const response = page.waitForResponse(value => value.request().method() === 'POST' && /\/api\/schools\/[^/]+\/confirm$/.test(value.url()))
  await page.getByRole('button', { name: '确认并生成方案', exact: true }).click()
  const confirmed = await response
  expect(confirmed.ok()).toBe(true)
  const result = await confirmed.json()
  await expect(page.getByRole('button', { name: '使用此方案检测', exact: true })).toBeEnabled()
  return result
}

test('模板SimSun与说明宋体可共同核对发布，并分别获得同一原稿的执行证据', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const manuscript = documentFixture('SimSun')
  await uploadTemplate(page, '匿名等价字体说明验收', manuscript)
  await page.locator('details.school-add-source > summary').click()
  await page.locator('#source-role').selectOption('instructions')
  await page.locator('input[type=file]').first().setInputFiles({ name: '匿名格式说明.txt', mimeType: 'text/plain', buffer: Buffer.from('正文使用宋体。') })
  await page.getByRole('button', { name: '上传并提取要求', exact: true }).click()
  await expect(page.locator('.source-list > details')).toHaveCount(2)
  const cards = requirementCards(page, 'body.fonts.eastAsia')
  const pagination = page.getByRole('navigation', { name: '学校要求分页', exact: true })
  let confirmedFonts = 0
  while (true) {
    await expect(page.locator('.requirement-editor').first()).toBeVisible()
    const count = await cards.count()
    for (let index = 0; index < count; index++) {
      await openRequirement(cards.nth(index))
      await cards.nth(index).getByRole('checkbox', { name: /确认第/ }).check()
      confirmedFonts += 1
    }
    if (!await pagination.count()) break
    const next = pagination.getByRole('button', { name: '下一页', exact: true })
    if (await next.isDisabled()) break
    const previousStatus = await pagination.getByRole('status').innerText()
    await next.click()
    await expect(pagination.getByRole('status')).not.toHaveText(previousStatus)
  }
  expect(confirmedFonts).toBe(2)
  const published = await publish(page)
  const fonts = published.profiles[0].requirements.filter((item: { target: string }) => item.target === 'body.fonts.eastAsia')
  expect(fonts.map((item: { expected: string }) => item.expected).sort()).toEqual(['SimSun', '宋体'])
  expect(new Set(fonts.map((item: { source_id: string }) => item.source_id)).size).toBe(2)
  await page.getByRole('button', { name: '使用此方案检测', exact: true }).click()
  await page.locator('input[type=file]').first().setInputFiles({ name: '匿名待检原稿.docx', mimeType: mime, buffer: manuscript })
  const scope = page.getByRole('region', { name: '原稿范围匹配' })
  await scope.getByRole('button', { name: '读取原稿范围', exact: true }).click()
  await expect(scope.getByText(/已处理 0\/2 条/)).toBeVisible()
  for (let index = 0; index < 2; index++) {
    await scope.getByLabel('查找原稿样式', { exact: true }).fill('Normal')
    const list = scope.getByRole('list', { name: '原稿中的段落样式' })
    await expect(list).toContainText('Normal')
    await list.getByRole('checkbox').check()
    await scope.getByRole('button', { name: '确认此范围', exact: true }).click()
    if (!index) await scope.getByRole('button', { name: '下一条范围要求', exact: true }).click()
  }
  await expect(scope.getByText(/已处理 2\/2 条，可以开始检测/)).toBeVisible()
  await page.getByRole('button', { name: '开始格式检测', exact: true }).click()
  await expect(page.getByRole('tab', { name: '问题明细' })).toBeVisible({ timeout: 45_000 })
  const jobId = page.url().split('#job/')[1]!
  const job = await (await request.get(`/api/jobs/${jobId}`)).json()
  const checks = job.result.coverage.checks.filter((item: { target: string; requirement_id?: string }) => item.target === 'body.fonts.eastAsia' && item.requirement_id)
  expect(checks.map((item: { status: string }) => item.status)).toEqual(['passed', 'passed'])
  expect(checks[0].observed_check_ids).toEqual(checks[1].observed_check_ids)
  expect(errors).toEqual([])
})

test('已发布模板分节要求可改为全文，重新发布后直接检查所有原稿分节', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const manuscript = documentFixture()
  await uploadTemplate(page, '匿名全文纸张范围验收', manuscript)
  let width = requirementCards(page, 'page.width_mm')
  await expect(width).toHaveCount(1)
  await openRequirement(width)
  await expect(width.getByRole('button', { name: '移除模板第 1 节', exact: true })).toBeVisible()
  await width.getByRole('checkbox', { name: /确认第/ }).check()
  const first = await publish(page)
  expect(first.profiles[0].requirements.find((item: { target: string }) => item.target === 'page.width_mm').scope_binding_status).toBe('unbound')
  width = requirementCards(page, 'page.width_mm')
  await openRequirement(width)
  await width.getByRole('button', { name: '移除模板第 1 节', exact: true }).click()
  await expect(width.locator('summary')).toContainText('全文要求')
  const second = await publish(page)
  const global = second.profiles[0].requirements.find((item: { target: string }) => item.target === 'page.width_mm')
  expect(global.scope_section_indices).toEqual([])
  expect(global.scope_binding_status).toBeUndefined()
  expect(global.source_scope_section_indices).toEqual([1])
  await page.getByRole('button', { name: '使用此方案检测', exact: true }).click()
  await page.locator('input[type=file]').first().setInputFiles({ name: '匿名待检原稿.docx', mimeType: mime, buffer: manuscript })
  await expect(page.getByRole('region', { name: '原稿范围匹配' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '开始格式检测', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '开始格式检测', exact: true }).click()
  await expect(page.getByRole('tab', { name: '问题明细' })).toBeVisible({ timeout: 45_000 })
  const jobId = page.url().split('#job/')[1]!
  const job = await (await request.get(`/api/jobs/${jobId}`)).json()
  const coverage = job.result.coverage.checks.find((item: { requirement_id?: string }) => item.requirement_id === global.id)
  expect(coverage.status).toBe('passed')
  expect(coverage.observed_check_ids).toHaveLength(1)
  expect(errors).toEqual([])
})
