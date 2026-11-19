import type { DocumentFormat } from '../types'

export const documentAccept = '.docx,.pdf,.txt,.md,.json'
export const maxDocumentBytes = 40 * 1024 * 1024
export function documentFormat(filename: string): DocumentFormat | undefined {
  const extension = filename.match(/\.([^.]+)$/)?.[1]?.toLowerCase()
  return ['docx', 'pdf', 'txt', 'md', 'json'].includes(extension || '') ? extension as DocumentFormat : undefined
}
export function documentFileError(file: Pick<File, 'name' | 'size'>): string {
  if (!documentFormat(file.name)) return '请选择 DOCX、PDF、TXT、MD 或 JSON 文档；.doc 文档请先另存为 DOCX。'
  if (file.size === 0 || file.size > maxDocumentBytes) return '文档必须非空且不超过 40 MB。'
  return ''
}
export function formatLabel(format?: string) { return format ? format.toUpperCase() : '未记录' }
export function extractionMethodLabel(method?: string) {
  return ({ text: '原生文本', native: '原生文本', extracted: '自动提取', ocr: '文字识别', mixed: '原生文本与文字识别', transcription: '人工核对转录', blank: '空白页', unavailable: '未取得文本', skipped: '未处理' } as Record<string, string>)[method || ''] || (method ? '其他读取方式' : '未记录')
}
