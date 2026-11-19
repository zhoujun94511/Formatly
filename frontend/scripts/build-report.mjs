import { createHash } from 'node:crypto'
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { build } from 'vite'

const root = fileURLToPath(new URL('../', import.meta.url))
const output = path.resolve(root, 'dist/report-template.html')
const temporary = output + '.tmp'

// A failed build must not serve a stale report renderer.
await rm(output, { force: true })
try {
  const projectLicense = await readFile(path.resolve(root, '../LICENSE'), 'utf8')
  const dependencyNotices = await readFile(path.join(root, 'public/THIRD_PARTY_NOTICES.txt'), 'utf8')
  const licenses = projectLicense.trimEnd() + '\n\n' + dependencyNotices.trimEnd()
  if (/<!--|-->|__FORMATLY_REPORT_[A-Z_]+__/.test(licenses)) {
    throw new Error('许可证文本不能包含 HTML 注释边界或报告模板标记')
  }
  const mark = await readFile(path.join(root, 'public/assets/formatly-mark.png'))
  const built = await build({
    configFile: false,
    root,
    publicDir: false,
    plugins: [vue()],
    define: {
      'process.env.NODE_ENV': JSON.stringify('production'),
      __FORMATLY_MARK_DATA_URL__: JSON.stringify('data:image/png;base64,' + mark.toString('base64')),
    },
    build: {
      write: false,
      emptyOutDir: false,
      target: 'es2022',
      assetsInlineLimit: Infinity,
      cssCodeSplit: false,
      sourcemap: false,
      lib: {
        entry: path.join(root, 'src/standalone-report.ts'),
        name: 'FormatlyStandaloneReport',
        formats: ['iife'],
        fileName: () => 'report.js',
      },
      rollupOptions: {
        output: { inlineDynamicImports: true },
      },
    },
  })
  const entries = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
  const chunks = entries.filter(entry => entry.type === 'chunk')
  const styles = entries.filter(entry => entry.type === 'asset' && entry.fileName.endsWith('.css'))
  if (chunks.length !== 1 || chunks[0].imports.length || chunks[0].dynamicImports.length) {
    throw new Error('离线报告必须生成一个包含 Vue 的独立脚本，不能依赖外部模块')
  }
  if (entries.length !== chunks.length + styles.length || !styles.length) {
    throw new Error('离线报告只能包含内联脚本与样式，不能输出相邻资源')
  }

  // Prevent HTML raw-text parsing from treating JS strings as closing elements.
  const script = chunks[0].code.replace(/<\/script/gi, match => '<\\/' + match.slice(2))
  if (script.includes('<!--')) {
    throw new Error('报告脚本含 HTML 注释起始符，不能安全内联')
  }
  const css = styles.map(entry => typeof entry.source === 'string'
    ? entry.source : Buffer.from(entry.source).toString('utf8'))
    .join('\n').replace(/<\/style/gi, match => '<\\/' + match.slice(2))
  const hash = createHash('sha256').update(script, 'utf8').digest('base64')
  const policy = `default-src 'none'; script-src 'sha256-${hash}'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'`

  let page = await readFile(path.join(root, 'scripts/report.html'), 'utf8')
  for (const token of ['TITLE', 'DATA', 'CSP', 'STYLES', 'SCRIPT', 'LICENSES']) {
    const marker = `__FORMATLY_REPORT_${token}__`
    if (page.split(marker).length !== 2) throw new Error('报告模板占位符须唯一：' + marker)
  }
  for (const [token, value] of [['CSP', policy], ['STYLES', css], ['SCRIPT', script], ['LICENSES', licenses]]) {
    page = page.replace(`__FORMATLY_REPORT_${token}__`, () => value)
  }
  await mkdir(path.dirname(output), { recursive: true })
  await writeFile(path.join(root, 'dist/LICENSE.txt'), projectLicense, 'utf8')
  await writeFile(temporary, page, 'utf8')
  await rename(temporary, output)
  console.log('已生成单文件 Vue 报告模板：' + path.relative(root, output))
} finally {
  await rm(temporary, { force: true })
}
