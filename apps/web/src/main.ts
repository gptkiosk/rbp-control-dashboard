import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { createAppRouter } from './router'
import './styles/main.css'
import { useThemeStore } from './stores/theme'

const pinia = createPinia()
const app = createApp(App).use(pinia).use(createAppRouter())
useThemeStore(pinia).start()
app.mount('#app')
