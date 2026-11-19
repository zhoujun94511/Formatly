import { onBeforeUnmount, onMounted, render, type Ref, type VNode } from 'vue'

// The browser's beforeprint event is synchronous. Mount a complete Vue copy
// there so Ctrl+P includes every issue and rule across all interactive pages.
export function useCompleteReportPrint(host: Ref<Element | undefined>, content: () => VNode, renderReport: typeof render = render) {
  let active = false, disposed = false
  function prepare() {
    if (disposed || !host.value) return
    renderReport(content(), host.value); active = true
  }
  function clear() { if (active && host.value) renderReport(null, host.value); active = false }
  function print() {
    if (disposed) return
    prepare()
    try { window.print() } finally { clear() }
  }
  onMounted(() => { window.addEventListener('beforeprint', prepare); window.addEventListener('afterprint', clear) })
  onBeforeUnmount(() => { disposed = true; window.removeEventListener('beforeprint', prepare); window.removeEventListener('afterprint', clear); clear() })
  return { print }
}
