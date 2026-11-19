/** Verify an HTTP-downloaded report in an isolated folder after its service stops. */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import net from 'node:net'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const args = new Map()
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index]
  assert.ok(key.startsWith('--') && process.argv[index + 1], 'Arguments use --name value')
  args.set(key.slice(2), process.argv[index + 1])
}
assert.ok(args.has('delivery') && args.has('output'), '--delivery and --output are required')
const deliveryPath = path.resolve(args.get('delivery'))
const output = path.resolve(args.get('output'))
const delivery = JSON.parse(await readFile(deliveryPath, 'utf8'))
assert.equal(delivery.schema, 'formatly.report-delivery.v1')
assert.equal(delivery.server_stopped, true)
assert.equal(delivery.original_unchanged, true)
assert.equal(delivery.input_snapshot_unchanged, true)
assert.deepEqual(delivery.offline_folder_files, ['report.html'])
const htmlDownload = delivery.http_downloads.find(item => item.filename === 'report.html')
assert.ok(htmlDownload?.attachment && htmlDownload.status === 200, 'Needs the successful HTTP attachment')
const reportPath = path.resolve(path.dirname(deliveryPath), htmlDownload.saved_as)
const reportURL = pathToFileURL(reportPath).href
const html = await readFile(reportPath)
const hash = createHash('sha256').update(html).digest('hex')
assert.equal(hash, htmlDownload.sha256)
const embedded = html.toString('utf8').match(/<script\b[^>]*id=["']formatly-report-data["'][^>]*>([\s\S]*?)<\/script>/i)
assert.ok(embedded, 'Report must embed its own result')
const payload = JSON.parse(embedded[1])
const issues = payload.result.issues || []
assert.ok(issues.length > 0, 'Choose a report with issues to exercise filters and search')

function isPortOpen(port) {
  return new Promise((resolve, reject) => {
    const connection = net.createConnection({ host: '127.0.0.1', port })
    connection.setTimeout(2000)
    connection.once('connect', () => { connection.destroy(); resolve(true) })
    connection.once('error', error => {
      connection.destroy()
      if (error.code === 'ECONNREFUSED') resolve(false)
      else reject(error)
    })
    connection.once('timeout', () => { connection.destroy(); reject(new Error('Could not establish closed-port state')) })
  })
}
assert.equal(await isPortOpen(delivery.service_port), false, 'Owned HTTP service must be stopped before file:// opens')
await mkdir(output, { recursive: false })
const require = createRequire(import.meta.url)
const { chromium } = require(args.get('playwright-module') || 'playwright')
const browser = await chromium.launch({
  headless: true,
  ...(args.has('browser') ? { executablePath: args.get('browser') } : {}),
  args: ['--no-sandbox', '--disable-background-networking', '--disable-component-update']
})
const evidence = {
  schema: 'formatly.offline-report-browser.v1', created_at: new Date().toISOString(),
  scope: 'report_delivery_only_not_school_accuracy', report_sha256: hash,
  report_template_sha256: delivery.report_template_sha256,
  input_sha256: delivery.input_sha256, browser: browser.version(),
  owned_service_stopped_before_browser: true, filters: [], viewports: [],
  unexpected_requests: [], page_errors: [], console_errors: [], passed: false
}
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const page = await context.newPage()
  page.on('request', request => {
    const url = request.url()
    if (url !== reportURL && !url.startsWith('data:') && !url.startsWith('blob:')) {
      evidence.unexpected_requests.push({ scheme: new URL(url).protocol, resource_type: request.resourceType() })
    }
  })
  page.on('pageerror', error => evidence.page_errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') evidence.console_errors.push(message.text()) })
  await context.route(/^https?:\/\//, route => route.abort('blockedbyclient'))
  await page.goto(reportURL, { waitUntil: 'load', timeout: 30000 })
  await page.locator('.report-content').waitFor({ state: 'visible', timeout: 10000 })
  assert.equal(await page.locator('.report-brand strong').innerText(), 'Formatly')
  assert.equal(await page.locator('.report-brand span').innerText(), 'Academic formatting, checked.')
  assert.equal(await page.locator('h1').innerText(), delivery.anonymous_filename)
  evidence.brand_image_embedded = await page.locator('.report-brand img').evaluate(image =>
    image.complete && image.naturalWidth > 0 && image.src.startsWith('data:image/'))
  assert.equal(evidence.brand_image_embedded, true)
  await page.keyboard.press('Tab')
  assert.equal(await page.locator('.skip-link').evaluate(element => element === document.activeElement), true)
  await page.keyboard.press('Enter')
  assert.equal(await page.locator('#main-content').evaluate(element => element === document.activeElement), true)
  evidence.skip_link_keyboard = true

  const filterNames = { all: '全部', error: '错误', warning: '风险提示', manual: '人工复核' }
  const cards = page.locator('.issues-panel .issue-card')
  async function expectCardCount(expected) {
    await page.waitForFunction(count => document.querySelectorAll('.issues-panel .issue-card').length === count, expected)
    assert.equal(await cards.count(), expected)
  }
  for (const [level, name] of Object.entries(filterNames)) {
    const button = page.getByRole('button', { name, exact: true })
    await button.click()
    const expected = level === 'all' ? issues.length : issues.filter(issue => issue.level === level).length
    await expectCardCount(expected)
    assert.equal(await button.getAttribute('aria-pressed'), 'true')
    evidence.filters.push({ level, expected, actual: await cards.count() })
  }
  const all = page.getByRole('button', { name: filterNames.all, exact: true })
  await all.focus()
  await page.keyboard.press('Enter')
  await expectCardCount(issues.length)
  evidence.filter_keyboard = true
  const search = page.getByRole('searchbox', { name: '搜索问题' })
  const query = issues[0].rule_id
  await search.fill(query)
  await page.waitForFunction(() => document.querySelector('input[type="search"]')?.value.length > 0)
  const searchable = value => value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value)
  const expectedSearch = issues.filter(issue => ['rule_id', 'location', 'message', 'expected', 'actual']
    .some(key => searchable(issue[key]).toLowerCase().includes(query.toLowerCase()))).length
  await expectCardCount(expectedSearch)
  evidence.search_matches = { expected: expectedSearch, actual: await cards.count() }
  await search.fill('__formatly_absent_query_64d7932e__')
  await expectCardCount(0)
  assert.equal(await page.locator('.issues-panel .empty-state').innerText(), '没有匹配的问题')
  evidence.empty_search = true
  await search.fill('')
  await expectCardCount(issues.length)
  await page.locator('.result-stat.error-stat').click()
  await expectCardCount(issues.filter(issue => issue.level === 'error').length)
  assert.equal(await page.locator('.issues-heading').evaluate(element => element === document.activeElement), true)
  evidence.summary_moves_focus = true
  await all.click()

  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.evaluate(async () => { await document.fonts.ready; await new Promise(requestAnimationFrame) })
    const dimensions = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth }))
    assert.ok(dimensions.content <= dimensions.viewport, `Horizontal overflow at ${width}px`)
    const font = await search.evaluate(element => ({ size: getComputedStyle(element).fontSize, family: getComputedStyle(element).fontFamily }))
    assert.ok(Number.parseFloat(font.size) >= 15, `Search font too small at ${width}px`)
    evidence.viewports.push({ width, ...dimensions, search_font_px: Number.parseFloat(font.size), font_family: font.family })
    await page.evaluate(() => scrollTo(0, 0))
    await page.screenshot({ path: path.join(output, `offline-${width}.png`), fullPage: false })
  }
  await page.reload({ waitUntil: 'load' })
  await page.locator('.report-content').waitFor({ state: 'visible' })
  await expectCardCount(issues.length)
  evidence.reload = true
  assert.equal(await isPortOpen(delivery.service_port), false)
  assert.deepEqual(evidence.unexpected_requests, [], 'Independent report requested adjacent or external resources')
  assert.deepEqual(evidence.page_errors, [])
  assert.deepEqual(evidence.console_errors, [])
  evidence.passed = true
} finally {
  await browser.close()
  await writeFile(path.join(output, 'browser.json'), JSON.stringify(evidence, null, 2) + '\n')
}
console.log(JSON.stringify({ passed: evidence.passed, input_sha256: evidence.input_sha256,
  filters: evidence.filters, viewports: evidence.viewports.map(item => item.width),
  unexpected_requests: evidence.unexpected_requests.length, page_errors: evidence.page_errors.length,
  console_errors: evidence.console_errors.length }))
