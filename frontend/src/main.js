import { createApp } from 'vue'
import '@fontsource-variable/roboto-mono'
import './styles/base.css'
import App from './App.vue'
import { router } from './router.js'

createApp(App).use(router).mount('#app')
