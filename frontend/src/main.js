import { createApp } from 'vue'
import '@fontsource-variable/roboto-mono'
import './styles/base.css'
import App from './App.vue'
import { router } from './router.js'

// Пока открывается первая страница, в #app видна заставка из index.html
// (в браузерной версии в это время загружается Python и база).
const app = createApp(App).use(router)
router.isReady().then(() => app.mount('#app'))
