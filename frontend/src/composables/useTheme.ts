import { computed, inject, readonly, ref, type InjectionKey, type Plugin } from 'vue'

export type Theme = 'light' | 'dark'
export const THEME_STORAGE_KEY = 'formatly.theme'
const validTheme = (value: unknown): Theme | null => value === 'light' || value === 'dark' ? value : null

export function createThemeController(target?: Window, documentTarget?: Document) {
  let media: MediaQueryList | undefined
  try { media = target?.matchMedia?.('(prefers-color-scheme: dark)') } catch { /* Use the default theme. */ }
  function readPreference(): Theme | null {
    try { return validTheme(target?.localStorage.getItem(THEME_STORAGE_KEY)) } catch { return null }
  }
  let preference = readPreference()
  const theme = ref<Theme>(preference ?? (media?.matches ? 'dark' : 'light'))
  let listening = false

  function apply() {
    theme.value = preference ?? (media?.matches ? 'dark' : 'light')
    documentTarget?.documentElement.setAttribute('data-theme', theme.value)
    documentTarget?.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme.value === 'dark' ? '#101722' : '#f7f8fa')
  }
  function setTheme(value: Theme) {
    const next = validTheme(value)
    if (!next) return
    preference = next
    try { target?.localStorage.setItem(THEME_STORAGE_KEY, next) } catch { /* Keep the current session's choice. */ }
    apply()
  }
  function systemChanged() { if (!preference) apply() }
  function storageChanged(event: StorageEvent) {
    if (event.key !== THEME_STORAGE_KEY && event.key !== null) return
    if (event.storageArea) {
      try { if (event.storageArea !== target?.localStorage) return } catch { return }
    }
    preference = event.key === null ? null : validTheme(event.newValue)
    apply()
  }
  function start() {
    if (listening) return
    listening = true
    apply()
    target?.addEventListener('storage', storageChanged)
    media?.addEventListener('change', systemChanged)
  }
  function stop() {
    if (!listening) return
    listening = false
    target?.removeEventListener('storage', storageChanged)
    media?.removeEventListener('change', systemChanged)
  }
  return { theme: readonly(theme), isDark: computed(() => theme.value === 'dark'), setTheme,
    toggle: () => setTheme(theme.value === 'dark' ? 'light' : 'dark'), start, stop }
}

const themeKey: InjectionKey<ReturnType<typeof createThemeController>> = Symbol('formatly-theme')
export const themePlugin: Plugin = {
  install(app) {
    const controller = createThemeController(typeof window === 'undefined' ? undefined : window,
      typeof document === 'undefined' ? undefined : document)
    controller.start()
    app.provide(themeKey, controller)
    app.onUnmount(controller.stop)
  },
}

export function useTheme() {
  const controller = inject(themeKey)
  if (!controller) throw new Error('主题组件需要安装 themePlugin。')
  return controller
}
