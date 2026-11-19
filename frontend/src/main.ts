import { createApp } from 'vue'
import App from './App.vue'
import { themePlugin } from './composables/useTheme'
import './styles/tokens.css'
import './styles/components.css'

createApp(App).use(themePlugin).mount('#app')
