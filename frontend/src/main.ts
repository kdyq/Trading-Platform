import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import './styles/tokens.css'
import './styles/base.css'

const app = createApp(App)
const pinia = createPinia()

app.config.errorHandler = (error) => {
  console.error('Unhandled application error', error)
}

app.use(pinia)
await useAuthStore(pinia).restore()
app.use(router)
app.mount('#app')
