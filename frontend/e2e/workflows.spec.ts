import { expect, test, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '../..')
const localPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const python = process.env.FORMATLY_TEST_PYTHON || (existsSync(localPython) ? localPython : 'python')
const pageErrors = new WeakMap<Page, string[]>()

test.beforeEach(({ page }) => {
  const errors: string[] = []
  pageErrors.set(page, errors)
  page.on('pageerror', error => errors.push(error.message))
})
test.afterEach(({ page }) => {
  expect(pageErrors.get(page)).toEqual([])
})

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
}

async function accessible(page: Page) {
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(result.violations.map(({ id, nodes }) => ({ id, elements: nodes.map(node => node.target) }))).toEqual([])
}

test('上传、真实检测、问题证据、复核与hash刷新', async ({ page }) => {
  await page.goto('/#new')
  await expect(page.getByRole('button', { name: '开始格式检测' })).toBeDisabled()
  await page.locator('#profile-select').selectOption('generic')
  await page.locator('input[type=file]').first().setInputFiles({ name: '匿名流程.txt', mimeType: 'text/plain', buffer: Buffer.from('摘要\n匿名论文流程样例\n参考文献\n[1] Example\n') })
  await expect(page.getByRole('button', { name: '开始格式检测' })).toBeEnabled()
  await page.getByRole('button', { name: '开始格式检测' }).click()
  await expect(page).toHaveURL(/#job\/[a-z0-9-]+$/)
  const taskUrl = page.url()
  await expect(page.getByRole('tab', { name: '问题明细' })).toBeVisible({ timeout: 45_000 })
  await page.reload()
  await expect(page).toHaveURL(taskUrl)
  await expect(page.getByRole('heading', { name: '匿名流程.txt', exact: true })).toBeVisible()
  await page.locator('.issue-summary').first().click()
  await page.getByRole('button', { name: '查看原稿与依据 / 复核' }).first().click()
  const dialog = page.getByRole('dialog', { name: '问题位置与依据' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByLabel('备注')).toBeEnabled()
  await dialog.getByLabel('备注').fill('未保存的匿名复核草稿')
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await page.evaluate(() => { location.hash = 'history' })
  await expect(page).toHaveURL(/#history$/)
  await page.evaluate(hash => { location.hash = hash }, taskUrl.split('#')[1]!)
  await expect(page.getByRole('heading', { name: '匿名流程.txt', exact: true })).toBeVisible()
  await page.locator('.issue-summary').first().click()
  await page.getByRole('button', { name: '查看原稿与依据 / 复核' }).first().click()
  await expect(dialog.getByLabel('备注')).toHaveValue('未保存的匿名复核草稿')
  await dialog.getByLabel('备注').fill('匿名浏览器复核意见')
  await dialog.getByRole('button', { name: '保存复核意见', exact: true }).click()
  await expect(dialog.getByText('复核意见已保存。')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(page.getByRole('button', { name: '查看原稿与依据 / 复核' }).first()).toBeFocused()
  await page.getByRole('button', { name: '查看原稿与依据 / 复核' }).first().click()
  await expect(dialog.getByLabel('备注')).toHaveValue('匿名浏览器复核意见')
  await accessible(page)
  await page.keyboard.press('Escape')
  await noOverflow(page)
})

test('学校说明上传、核对、方案调用', async ({ page }) => {
  await page.goto('/#schools/new')
  await page.getByLabel('学校要求名称').fill('匿名浏览器学校要求')
  await page.locator('input[type=file]').first().setInputFiles({ name: '学校说明.txt', mimeType: 'text/plain', buffer: Buffer.from('纸张采用A4。\n页边距上30毫米，下25毫米，左25毫米，右25毫米。') })
  await page.getByRole('button', { name: '上传并提取要求', exact: true }).click()
  await expect(page.getByText('已上传来源', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: /核对格式要求/ })).toBeVisible()
  const requirements = page.locator('.requirement-editor')
  const count = await requirements.count()
  expect(count).toBeGreaterThan(0)
  for (let index = 0; index < count; index++) {
    const item = requirements.nth(index)
    if (!(await item.getByRole('checkbox', { name: `确认第 ${index + 1} 条要求`, exact: true }).isVisible())) await item.locator('summary').first().click()
    await item.getByRole('checkbox', { name: `确认第 ${index + 1} 条要求`, exact: true }).check()
  }
  await page.getByRole('checkbox', { name: '已核对来源、材料类型和要求值；无法自动检查的内容已选人工复核。' }).check()
  await expect(page.getByRole('button', { name: '确认并生成方案', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '确认并生成方案', exact: true }).click()
  await expect(page.getByRole('button', { name: '使用此方案检测', exact: true })).toBeVisible()
  await noOverflow(page)
  await accessible(page)
  await page.locator('.page-heading').getByRole('button', { name: '检测原稿', exact: true }).click()
  await expect(page).toHaveURL(/#new\?profile=/)
  await expect(page.locator('#profile-select option:checked')).toContainText('匿名浏览器学校要求')
})

test('双材料来源经候选确认生成方案、顶部明确选择并检测', async ({ page, request }) => {
  await page.goto('/#schools/new')
  await expect(page.getByRole('status')).toContainText('放入学校模板或格式说明')
  await expect(page.getByRole('button', { name: '上传并提取要求', exact: true })).toBeVisible()
  await page.getByLabel('学校要求名称').fill('匿名通用多方案')
  await page.locator('#source-role').selectOption('instructions')
  await page.locator('input[type=file]').first().setInputFiles({ name: '论文纸张说明.txt', mimeType: 'text/plain', buffer: Buffer.from('纸张采用A4。') })
  await page.getByRole('button', { name: '上传并提取要求', exact: true }).click()
  await expect(page.getByRole('heading', { name: '已上传来源', exact: true })).toBeVisible()
  await page.locator('details.school-add-source > summary').click()
  await page.locator('#source-kind').selectOption('intern')
  await page.locator('input[type=file]').first().setInputFiles({ name: '报告纸张说明.txt', mimeType: 'text/plain', buffer: Buffer.from('纸张采用A4。') })
  await page.getByRole('button', { name: '上传并提取要求', exact: true }).click()
  await expect(page.locator('.source-list > details')).toHaveCount(2)
  const requirements = page.locator('.requirement-editor')
  expect(await requirements.count()).toBeGreaterThanOrEqual(4)
  for (let index = 0; index < await requirements.count(); index++) {
    const item = requirements.nth(index)
    const confirmation = item.getByRole('checkbox', { name: `确认第 ${index + 1} 条要求`, exact: true })
    if (!(await confirmation.isVisible())) await item.locator('summary').first().click()
    await confirmation.check()
  }
  await page.getByRole('checkbox', { name: '已核对来源、材料类型和要求值；无法自动检查的内容已选人工复核。' }).check()
  await page.getByRole('button', { name: '确认并生成方案', exact: true }).click()
  await expect(page.locator('.school-profile-list > li')).toHaveCount(2)
  const schoolUrl = page.url()
  await page.locator('.page-heading').getByRole('button', { name: '选择方案检测', exact: true }).click()
  await expect(page.locator('.generated-profiles')).toBeFocused()
  await expect(page).toHaveURL(schoolUrl)
  await page.locator('.school-profile-list > li').filter({ hasText: '毕业实习报告' }).getByRole('button', { name: '使用此方案检测', exact: true }).click()
  await expect(page).toHaveURL(/#new\?profile=school-[^&]+&kind=intern$/)
  await expect(page.locator('#kind-select')).toHaveValue('intern')
  const selectedProfile = await page.locator('#profile-select').inputValue()
  await expect(page.locator('#profile-select option:checked')).toContainText('匿名通用多方案')
  const document = execFileSync(python, ['-B', '-c', 'import sys; from scripts.sample_inputs import fixtures; sys.stdout.buffer.write(fixtures()["docx"])'], { cwd: root })
  await page.locator('input[type=file]').first().setInputFiles({ name: '匿名实习报告.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: document })
  await page.getByRole('button', { name: '开始格式检测', exact: true }).click()
  await expect(page.getByRole('tab', { name: '问题明细' })).toBeVisible({ timeout: 45_000 })
  const task = await (await request.get(`/api/jobs/${page.url().split('#job/')[1]!}`)).json()
  expect(task.status).toBe('completed')
  expect(task.result.profile_id).toBe(selectedProfile)
  expect(task.result.kind).toBe('intern')
  expect(task.result.execution_errors).toBe(0)
  expect(task.result.coverage.checks.some((check: { target: string; status: string }) => check.target === 'page.width_mm' && check.status === 'passed')).toBe(true)
  await accessible(page)
  await noOverflow(page)
})

test('DOCX选择修复、副本复检及原稿保留', async ({ page, request }) => {
  // The explicit OOXML deviation is created before detection, without an
  // office renderer, private documents, or expected report data as input.
  const document = execFileSync(python, ['-B', '-c', [
    'from io import BytesIO',
    'from zipfile import ZipFile',
    'import sys',
    'from scripts.sample_inputs import fixtures',
    'source = ZipFile(BytesIO(fixtures()["docx"]))',
    'output = BytesIO()',
    'with ZipFile(output, "w") as target:',
    ' for name in source.namelist():',
    '  data = source.read(name)',
    '  if name == "word/document.xml": data = data.replace(b\'w:w="11906"\', b\'w:w="13000"\')',
    '  target.writestr(name, data)',
    'sys.stdout.buffer.write(output.getvalue())',
  ].join('\n')], { cwd: root })
  await page.goto('/#new')
  await page.locator('#profile-select').selectOption('generic')
  await page.locator('input[type=file]').first().setInputFiles({ name: '匿名格式偏差.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: document })
  await page.getByRole('button', { name: '开始格式检测' }).click()
  await expect(page.getByRole('tab', { name: '修复与报告' })).toBeVisible({ timeout: 45_000 })
  const originalId = page.url().split('#job/')[1]!
  const original = await (await request.get(`/api/jobs/${originalId}`)).json()
  await page.getByRole('tab', { name: '修复与报告' }).click()
  await page.getByRole('button', { name: '查看可修复项' }).click()
  await expect(page.getByRole('heading', { name: '可修复 1 项', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '生成副本并复检' })).toBeDisabled()
  await page.locator('.repair-choices input[type=checkbox]').check()
  await page.getByRole('button', { name: '生成副本并复检' }).click()
  await expect(page).not.toHaveURL(new RegExp(`#job/${originalId}$`))
  await expect(page.getByRole('tab', { name: '问题明细' })).toBeVisible({ timeout: 45_000 })
  const repairedId = page.url().split('#job/')[1]!
  const repaired = await (await request.get(`/api/jobs/${repairedId}`)).json()
  expect(repaired.repair.source_job_id).toBe(originalId)
  expect(repaired.result.input_sha256).not.toBe(original.result.input_sha256)
  const unchanged = await (await request.get(`/api/jobs/${originalId}`)).json()
  expect(unchanged.result.input_sha256).toBe(original.result.input_sha256)
  await accessible(page)
})

test.describe('独立空数据布局', () => {
  test.use({ baseURL: `http://127.0.0.1:${Number(process.env.FORMATLY_TEST_LAYOUT_PORT || 18780)}` })
  for (const width of [320, 768, 1440, 2560]) {
    for (const theme of ['light', 'dark'] as const) {
      test(`静态入口布局 ${width}px ${theme}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1000 })
        await page.addInitScript(value => localStorage.setItem('formatly.theme', value), theme)
        for (const [route, heading] of [['new', '新建检测'], ['schools/new', '学校要求']] as const) {
          await page.goto(`/#${route}`)
          await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
          await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
          await page.evaluate(() => document.fonts.ready)
          await noOverflow(page)
          await accessible(page)
          const screenshotName = `${route.replace('/', '-')}-${width}-${theme}`
          const mask = [page.locator('.recent-section .panel'), page.locator('.stat-grid')]
          await test.info().attach(`${screenshotName}-actual`, {
            body: await page.screenshot({ fullPage: true, mask }), contentType: 'image/png',
          })
          if (process.env.FORMATLY_COMPARE_SCREENSHOTS === '1') {
            await expect(page).toHaveScreenshot(`${screenshotName}.png`, { fullPage: true, mask })
          }
        }
      })
    }
  }
})
