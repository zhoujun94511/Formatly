import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '../..')
const localPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const python = process.env.FORMATLY_TEST_PYTHON || (existsSync(localPython) ? localPython : 'python')
const mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

function fixture(name: 'anonymous_template' | 'anonymous_manuscript', correct = false) {
  const argumentsText = name === 'anonymous_manuscript' && correct ? '(correct=True)' : '()'
  return execFileSync(python, ['-B', '-c', `import sys; sys.path.insert(0, 'tests'); from test_generic_scope_workflow import ${name}; sys.stdout.buffer.write(${name}${argumentsText})`], { cwd: root })
}

async function publishedScopeProfile(request: APIRequestContext, name: string) {
  const created = await request.post('/api/schools', { data: { name } })
  expect(created.ok()).toBe(true)
  const school = await created.json()
  const uploaded = await request.post(`/api/schools/${school.id}/sources`, { multipart: {
    kind: 'thesis', role: 'template', source: { name: '匿名范围模板.docx', mimeType: mime, buffer: fixture('anonymous_template') },
  } })
  expect(uploaded.ok()).toBe(true)
  const source = await uploaded.json()
  const requirements = source.candidates.filter((item: { target: string }) => item.target === 'body.size_pt')
    .map((item: Record<string, unknown>) => ({ ...item, confirmed: true }))
  expect(requirements).toHaveLength(2)
  const confirmed = await request.post(`/api/schools/${school.id}/confirm`, { data: { requirements, expected_version: source.version } })
  expect(confirmed.ok()).toBe(true)
  return (await confirmed.json()).profiles[0]
}

async function auditPage(page: Page) {
  await page.evaluate(async () => {
    await document.fonts.ready
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
    await Promise.all(document.getAnimations().filter(animation =>
      Number.isFinite(animation.effect?.getComputedTiming().endTime)).map(animation =>
      animation.finished.catch(() => undefined)))
  })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  const findings = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(findings.violations.map(item => ({ id: item.id,
    nodes: item.nodes.map(node => ({ target: node.target, summary: node.failureSummary })) }))).toEqual([])
}

test('通用模板与陌生说明经核对、不同原稿范围、检测及针对性修复复检', async ({ page, request }) => {
  const pageErrors: string[] = []
  page.on('pageerror', error => pageErrors.push(error.message))
  const template = fixture('anonymous_template')
  const manuscript = fixture('anonymous_manuscript')
  const clause = '所有标题须按大纲保持层级连续，不得从一级直接跳到三级。章标题采用一级，并在章前分页。参考文献被引情况本次暂不启用。'
  await page.goto('/#schools/new')
  await page.getByLabel('学校要求名称').fill('匿名通用范围及结构验收')
  await page.locator('input[type=file]').first().setInputFiles({ name: '匿名双范围模板.docx', mimeType: mime, buffer: template })
  await page.getByRole('button', { name: '上传并提取要求', exact: true }).click()
  await expect(page.getByRole('heading', { name: '已上传来源', exact: true })).toBeVisible()
  await page.locator('details.school-add-source > summary').click()
  await page.locator('#source-role').selectOption('instructions')
  await page.locator('input[type=file]').first().setInputFiles({ name: '陌生格式说明.txt', mimeType: 'text/plain', buffer: Buffer.from(clause) })
  await page.getByRole('button', { name: '上传并提取要求', exact: true }).click()
  await expect(page.locator('.source-list > details')).toHaveCount(2)
  const sourceUrl = page.url()
  const schoolId = sourceUrl.split('#schools/')[1]!
  const schoolBefore = await (await request.get(`/api/schools/${schoolId}`)).json()
  const sizes = page.locator('.requirement-editor').filter({ has: page.locator('summary', { hasText: '模板正文样式字号候选' }) })
  await expect(sizes).toHaveCount(2)
  for (let index = 0; index < 2; index++) {
    const card = sizes.nth(index)
    await card.locator('summary').click()
    await card.getByRole('checkbox', { name: /确认第/ }).check()
  }
  // Structural clauses come from this uploaded source and are explicitly
  // entered and confirmed by the user; they are not counted as extraction hits.
  for (const item of [
    { label: '标题层级须连续', target: 'structure.headings.hierarchy', value: 'true' },
    { label: '一级章标题须章前分页', target: 'structure.headings.chapter_page_break', value: 'true', chapterLevel: '1' },
    { label: '本次关闭参考文献被引检查', target: 'structure.references.require_all_cited', value: 'false' },
  ]) {
    await page.getByRole('button', { name: '添加要求', exact: true }).click()
    const card = page.locator('.requirement-editor').last()
    await card.getByLabel('要求名称', { exact: true }).fill(item.label)
    await card.getByLabel('执行方式', { exact: true }).selectOption('automatic')
    await card.getByLabel('检查目标', { exact: true }).selectOption(item.target)
    await card.getByLabel('要求值', { exact: true }).selectOption(item.value)
    if (item.chapterLevel) await card.getByLabel('章标题级别', { exact: true }).fill(item.chapterLevel)
    await card.getByLabel('依据文件', { exact: true }).selectOption({ label: '陌生格式说明.txt' })
    await card.getByLabel('出处定位', { exact: true }).fill('第1行')
    await card.getByLabel('原文摘录', { exact: true }).fill(clause)
    await card.getByRole('checkbox', { name: /确认第/ }).check()
  }
  await page.getByRole('checkbox', { name: '已核对来源、材料类型和要求值；无法自动检查的内容已选人工复核。' }).check()
  await page.getByRole('button', { name: '确认并生成方案', exact: true }).click()
  await expect(page.getByRole('button', { name: '使用此方案检测', exact: true })).toBeVisible()
  await page.locator('.page-heading').getByRole('button', { name: '检测原稿', exact: true }).click()
  const profileId = await page.locator('#profile-select').inputValue()
  const sourceProfile = await (await request.get(`/api/profiles/${profileId}`)).json()
  await page.locator('input[type=file]').first().setInputFiles({ name: '不同样式的匿名原稿.docx', mimeType: mime, buffer: manuscript })
  const scope = page.getByRole('region', { name: '原稿范围匹配' })
  await expect(scope).toBeVisible()
  await expect(page.getByRole('button', { name: '开始格式检测', exact: true })).toBeDisabled()
  let currentPreviewId = ''
  async function confirmManuscriptScopes() {
    const reading = page.waitForResponse(response => response.request().method() === 'POST'
      && response.url().endsWith('/api/document-previews'))
    await scope.getByRole('button', { name: '读取原稿范围', exact: true }).click()
    currentPreviewId = (await (await reading).json()).id
    await expect(scope.getByText(/已处理 0\/2 条/)).toBeVisible()
    for (let index = 0; index < 2; index++) {
      const active = await scope.locator('.scope-requirement').innerText()
      const style = /要求值：12/.test(active) ? 'UserMain' : 'UserAppendix'
      await scope.getByLabel('查找原稿样式', { exact: true }).fill(style)
      const list = scope.getByRole('list', { name: '原稿中的段落样式' })
      await expect(list).toContainText(style)
      await list.getByRole('checkbox').check()
      await scope.getByRole('button', { name: '确认此范围', exact: true }).click()
      if (!index) await scope.getByRole('button', { name: '下一条范围要求', exact: true }).click()
    }
    await expect(scope.getByText(/已处理 2\/2 条，可以开始检测/)).toBeVisible()
  }
  await confirmManuscriptScopes()
  // An identically named replacement is a different input. Its prior choices
  // must disappear; then reselect and confirm the actual final manuscript.
  await page.locator('input[type=file]').first().setInputFiles({ name: '不同样式的匿名原稿.docx', mimeType: mime, buffer: fixture('anonymous_manuscript', true) })
  await expect(scope.getByRole('button', { name: '读取原稿范围', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '开始格式检测', exact: true })).toBeDisabled()
  await page.locator('input[type=file]').first().setInputFiles({ name: '不同样式的匿名原稿.docx', mimeType: mime, buffer: manuscript })
  await confirmManuscriptScopes()
  await page.setViewportSize({ width: 1280, height: 1100 })
  await scope.scrollIntoViewIfNeeded()
  await auditPage(page)
  await test.info().attach('原稿两范围已明确确认', { body: await scope.screenshot(), contentType: 'image/png' })
  await page.setViewportSize({ width: 320, height: 1000 })
  await scope.scrollIntoViewIfNeeded()
  await auditPage(page)
  const confirmBounds = await scope.getByRole('button', { name: '确认此范围', exact: true }).boundingBox()
  const manualBounds = await scope.getByRole('button', { name: '暂不匹配', exact: true }).boundingBox()
  expect(confirmBounds).not.toBeNull()
  expect(manualBounds).not.toBeNull()
  expect(confirmBounds!.x + confirmBounds!.width <= manualBounds!.x
    || manualBounds!.x + manualBounds!.width <= confirmBounds!.x
    || confirmBounds!.y + confirmBounds!.height <= manualBounds!.y
    || manualBounds!.y + manualBounds!.height <= confirmBounds!.y).toBe(true)
  await test.info().attach('320像素已展开并选择原稿范围', { body: await scope.screenshot(), contentType: 'image/png' })
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.getByRole('button', { name: '开始格式检测', exact: true }).click()
  await expect(page.getByRole('tab', { name: '问题明细' })).toBeVisible({ timeout: 45_000 })
  const originalId = page.url().split('#job/')[1]!
  const original = await (await request.get(`/api/jobs/${originalId}`)).json()
  expect(original.status).toBe('completed')
  await expect.poll(async () => (await request.get(`/api/document-previews/${currentPreviewId}/styles`)).status()).toBe(400)
  const checks = original.result.coverage.checks as { target: string; expected: unknown; actual: unknown; status: string; requirement_id?: string }[]
  expect(checks.filter(item => item.target === 'body.size_pt' && item.requirement_id).map(item => [item.expected, item.status]).sort()).toEqual([[10, 'failed'], [12, 'failed']])
  expect(checks.some(item => item.target === 'structure.headings.hierarchy' && item.status === 'passed')).toBe(true)
  expect(checks.some(item => item.target === 'structure.headings.chapter_page_break' && item.status === 'failed')).toBe(true)
  expect(checks.filter(item => item.target === 'structure.references.require_all_cited').map(item => item.status)).toEqual(['not_checked'])
  expect(original.result.scope_bindings.items.map((item: { style_ids: string[] }) => item.style_ids)).toEqual([['UserMain'], ['UserAppendix']])
  await page.getByRole('tab', { name: '修复与报告' }).click()
  await page.getByRole('button', { name: '查看可修复项', exact: true }).click()
  await expect(page.getByRole('heading', { name: '可修复 2 项', exact: true })).toBeVisible()
  const plan = await (await request.get(`/api/jobs/${originalId}/repairs`)).json()
  const selected = plan.candidates.find((item: { expected: number }) => item.expected === 12)
  await page.locator(`.repair-choices input[value="${selected.id}"]`).check()
  await page.getByRole('button', { name: '生成副本并复检', exact: true }).click()
  await expect(page).not.toHaveURL(new RegExp(`#job/${originalId}$`))
  await expect(page.getByRole('tab', { name: '问题明细' })).toBeVisible({ timeout: 45_000 })
  const repairedId = page.url().split('#job/')[1]!
  const repaired = await (await request.get(`/api/jobs/${repairedId}`)).json()
  expect(repaired.status).toBe('completed')
  expect(repaired.repair.source_job_id).toBe(originalId)
  expect(repaired.result.input_sha256).not.toBe(original.result.input_sha256)
  expect(repaired.result.scope_bindings.input_sha256).toBe(repaired.result.input_sha256)
  const repairedChecks = repaired.result.coverage.checks as typeof checks
  expect(repairedChecks.some(item => item.target === 'body.size_pt' && item.expected === 12 && item.status === 'passed')).toBe(true)
  expect(repairedChecks.some(item => item.target === 'body.size_pt' && item.expected === 10 && item.status === 'failed')).toBe(true)
  expect(await (await request.get(`/api/profiles/${profileId}`)).json()).toEqual(sourceProfile)
  const schoolAfter = await (await request.get(`/api/schools/${schoolId}`)).json()
  expect(schoolAfter.sources).toEqual(schoolBefore.sources)
  const originalAgain = await (await request.get(`/api/jobs/${originalId}`)).json()
  expect(originalAgain.result).toEqual(original.result)
  await page.reload()
  await expect(page.getByRole('heading', { name: '不同样式的匿名原稿-修复.docx', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '检测修改稿', exact: true })).toBeEnabled()
  await auditPage(page)
  expect(pageErrors).toEqual([])
})

test('无需学校上传的预置方案快速检测保留独立入口', async ({ page, request }) => {
  const previews: string[] = []
  page.on('request', item => { if (item.url().includes('/api/document-previews')) previews.push(item.url()) })
  const before = await (await request.get('/api/schools')).json()
  await page.goto('/#new')
  await page.locator('#profile-select').selectOption('generic')
  await page.locator('input[type=file]').first().setInputFiles({ name: '预置快速检测.txt', mimeType: 'text/plain', buffer: Buffer.from('匿名论文正文。') })
  await expect(page.getByRole('region', { name: '原稿范围匹配' })).not.toBeVisible()
  await page.getByRole('button', { name: '开始格式检测', exact: true }).click()
  await expect(page.getByRole('tab', { name: '问题明细' })).toBeVisible({ timeout: 45_000 })
  const job = await (await request.get(`/api/jobs/${page.url().split('#job/')[1]!}`)).json()
  expect(job.status).toBe('completed')
  expect(job.profile_id).toBe('generic')
  expect(previews).toEqual([])
  expect(await (await request.get('/api/schools')).json()).toEqual(before)
})

test('学校方案经界面复制及导出导入后仍可刷新读取并保留分范围规则', async ({ page, request }) => {
  const source = await publishedScopeProfile(request, '匿名方案复制与导入验收')
  await page.goto('/#profiles')
  const search = page.getByRole('searchbox', { name: '搜索规则方案' })
  await search.fill(source.name)
  await page.getByRole('button', { name: '复制方案', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('方案名称', { exact: true }).fill('匿名范围副本')
  const copiedResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/api/profiles'))
  await dialog.getByRole('button', { name: '保存方案', exact: true }).click()
  const copiedReceipt = await copiedResponse
  expect(copiedReceipt.status()).toBe(201)
  const copied = await copiedReceipt.json()
  await expect(dialog).not.toBeVisible()
  await page.reload()
  await search.fill('匿名范围副本')
  await expect(page.locator('.profile-card')).toHaveCount(1)
  expect((await (await request.get(`/api/profiles/${copied.id}`)).json()).scoped_rules).toEqual(source.scoped_rules)
  expect(copied.school.source_profile_id).toBe(source.id)
  await page.getByText('方案详情与更多操作', { exact: true }).click()
  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出 JSON', exact: true }).click()
  const downloaded = await downloading
  const exported = readFileSync((await downloaded.path())!)
  expect(JSON.parse(exported.toString()).scoped_rules).toEqual(source.scoped_rules)
  await page.getByLabel('导入规则方案 JSON', { exact: true }).setInputFiles({ name: '匿名方案.json', mimeType: 'application/json', buffer: exported })
  await dialog.getByLabel('方案名称', { exact: true }).fill('匿名范围导入副本')
  const importedResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/api/profiles'))
  await dialog.getByRole('button', { name: '保存方案', exact: true }).click()
  const importedReceipt = await importedResponse
  expect(importedReceipt.status()).toBe(201)
  const imported = await importedReceipt.json()
  expect(imported.school.source_profile_id).toBe(source.id)
  await page.reload()
  await search.fill('匿名范围导入副本')
  await expect(page.locator('.profile-card')).toHaveCount(1)
  const restored = await (await request.get(`/api/profiles/${imported.id}`)).json()
  expect(restored.requirements).toEqual(source.requirements)
  expect(restored.scoped_rules).toEqual(source.scoped_rules)
  await page.getByRole('button', { name: '使用此方案', exact: true }).click()
  await expect(page.locator('#profile-select')).toHaveValue(imported.id)
  await page.locator('input[type=file]').first().setInputFiles({ name: '副本检测原稿.docx', mimeType: mime, buffer: fixture('anonymous_manuscript') })
  await expect(page.getByRole('region', { name: '原稿范围匹配' })).toBeVisible()
  await expect(page.getByRole('button', { name: '开始格式检测', exact: true })).toBeDisabled()
})

test('批量界面分别确认两份原稿范围并得到对应的字号检测结果', async ({ page, request }) => {
  const source = await publishedScopeProfile(request, '匿名批量范围验收')
  const pageErrors: string[] = []
  page.on('pageerror', error => pageErrors.push(error.message))
  await page.goto('/#batch')
  await page.getByRole('combobox', { name: '规则方案', exact: true }).selectOption(source.id)
  await page.locator('input[type=file]').setInputFiles([
    { name: '匿名占位稿.docx', mimeType: mime, buffer: fixture('anonymous_manuscript') },
    { name: '匿名待修复.docx', mimeType: mime, buffer: fixture('anonymous_manuscript') },
    { name: '匿名正确排版.docx', mimeType: mime, buffer: fixture('anonymous_manuscript', true) },
  ])
  const submit = page.getByRole('button', { name: /^开始检测/ })
  const picker = page.getByRole('combobox', { name: '当前原稿', exact: true })
  const scope = page.getByRole('region', { name: '原稿范围匹配' })
  await expect(submit).toBeDisabled()
  for (const index of ['1', '2']) {
    await picker.selectOption(index)
    await scope.getByRole('button', { name: '读取原稿范围', exact: true }).click()
    await expect(scope.getByText(/已处理 0\/2 条/)).toBeVisible()
    for (let requirement = 0; requirement < 2; requirement++) {
      const text = await scope.locator('.scope-requirement').innerText()
      const style = /要求值：12/.test(text) ? 'UserMain' : 'UserAppendix'
      await scope.getByLabel('查找原稿样式', { exact: true }).fill(style)
      const list = scope.getByRole('list', { name: '原稿中的段落样式' })
      await expect(list).toContainText(style)
      await list.getByRole('checkbox').check()
      await scope.getByRole('button', { name: '确认此范围', exact: true }).click()
      if (!requirement) await scope.getByRole('button', { name: '下一条范围要求', exact: true }).click()
    }
    await expect(scope.getByText(/已处理 2\/2 条，可以开始检测/)).toBeVisible()
  }
  await picker.selectOption('0')
  await page.getByRole('button', { name: '移除匿名占位稿.docx', exact: true }).click()
  await expect(picker).toHaveValue('0')
  await expect(scope.getByText(/已处理 2\/2 条，可以开始检测/)).toBeVisible()
  await expect(submit).toBeEnabled()
  await page.setViewportSize({ width: 320, height: 1100 })
  await auditPage(page)
  await page.setViewportSize({ width: 1280, height: 900 })
  const creating = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/api/batches'))
  await submit.click()
  const receipt = await creating
  expect(receipt.status()).toBe(202)
  const created = await receipt.json()
  expect(created.items).toHaveLength(2)
  await expect(page).toHaveURL(new RegExp(`#batch/${created.batch_id}$`))
  for (const [index, item] of created.items.entries()) {
    await expect.poll(async () => (await (await request.get(`/api/jobs/${item.job_id}`)).json()).status, { timeout: 45_000 }).toBe('completed')
    const job = await (await request.get(`/api/jobs/${item.job_id}`)).json()
    const checks = job.result.coverage.checks.filter((check: { target: string; requirement_id?: string }) => check.target === 'body.size_pt' && check.requirement_id)
    expect(checks.map((check: { expected: number; status: string }) => [check.expected, check.status]).sort()).toEqual(
      index === 0 ? [[10, 'failed'], [12, 'failed']] : [[10, 'passed'], [12, 'passed']])
    expect(job.result.scope_bindings.input_sha256).toBe(job.result.input_sha256)
    expect(job.result.scope_bindings.items.map((binding: { style_ids: string[] }) => binding.style_ids)).toEqual([['UserMain'], ['UserAppendix']])
  }
  await page.reload()
  await expect(page.getByRole('heading', { name: '本批结果', exact: true })).toBeVisible()
  await expect(page.locator('.batch-results > li')).toHaveCount(2)
  expect(pageErrors).toEqual([])
})

test('普通方案可直接检测，开始范围匹配后须完成或明确退出', async ({ page, request }) => {
  const profileId = 'optional-scope-ui'
  const saved = await request.post('/api/profiles', { data: {
    id: profileId, name: '匿名普通方案范围交互验收', plugins: ['docx-package', 'generic-format'],
    settings: { body: { font: '宋体', size_pt: 12, style_ids: ['Normal'] } }, kinds: ['thesis'],
  } })
  expect(saved.status()).toBe(201)
  const pageErrors: string[] = [], previews: string[] = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('request', item => { if (item.method() === 'POST' && item.url().endsWith('/api/document-previews')) previews.push(item.url()) })
  await page.goto('/#new')
  await page.locator('#profile-select').selectOption(profileId)
  await page.locator('input[type=file]').first().setInputFiles({ name: '普通方案匿名原稿.docx', mimeType: mime, buffer: fixture('anonymous_manuscript') })
  const submit = page.getByRole('button', { name: '开始格式检测', exact: true })
  const scope = page.getByRole('region', { name: '原稿范围匹配' })
  await expect(submit).toBeEnabled()
  expect(previews).toEqual([])

  async function startReview() {
    await scope.getByRole('button', { name: '读取原稿范围', exact: true }).click()
    await expect(scope.getByText(/已处理 0\/2 条/)).toBeVisible()
    await expect(submit).toBeDisabled()
  }
  async function confirmFirstRange() {
    await scope.getByRole('searchbox', { name: '查找原稿样式', exact: true }).fill('UserMain')
    const list = scope.getByRole('list', { name: '原稿中的段落样式' })
    await expect(list).toContainText('UserMain')
    await list.getByRole('checkbox').check()
    await scope.getByRole('button', { name: '确认此范围', exact: true }).click()
    await expect(scope.getByText(/已处理 1\/2 条/)).toBeVisible()
  }
  await startReview()
  await confirmFirstRange()
  await expect(submit).toBeDisabled()
  await scope.getByRole('button', { name: '退出匹配，使用原方案', exact: true }).click()
  await expect(scope.getByRole('button', { name: '读取原稿范围', exact: true })).toBeVisible()
  await expect(submit).toBeEnabled()

  await startReview()
  await confirmFirstRange()
  await scope.getByRole('button', { name: '下一条范围要求', exact: true }).click()
  await scope.getByRole('button', { name: '暂不匹配', exact: true }).click()
  await expect(scope.getByText(/已处理 2\/2 条，可以开始检测/)).toBeVisible()
  await expect(submit).toBeEnabled()
  const creating = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/api/jobs'))
  await submit.click()
  const receipt = await creating
  expect(receipt.status()).toBe(202)
  expect(receipt.request().postData()).toContain('name="scope_bindings"')
  const created = await receipt.json()
  await expect.poll(async () => (await (await request.get(`/api/jobs/${created.id}`)).json()).status, { timeout: 45_000 }).toBe('completed')
  const job = await (await request.get(`/api/jobs/${created.id}`)).json()
  expect(job.profile_id).toBe(profileId)
  expect(job.result.scope_bindings.input_sha256).toBe(job.result.input_sha256)
  expect(job.result.scope_bindings.items.map((item: { status: string }) => item.status)).toEqual(['bound', 'unbound'])
  expect(job.result.scope_bindings.items[0].style_ids).toEqual(['UserMain'])
  expect(previews).toHaveLength(2)
  expect(pageErrors).toEqual([])
})
