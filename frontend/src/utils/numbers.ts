const compactCount = new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 })

export function displayCount(value: number | string): string {
  return typeof value === 'number' && Number.isFinite(value) && Math.abs(value) >= 10000
    ? compactCount.format(value) : String(value)
}
