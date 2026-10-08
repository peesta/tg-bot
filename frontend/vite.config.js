import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// В разработке (npm run dev) запросы /api уходят на FastAPI: python main.py.
// npm run dev:pages и build:pages — версия для Cloudflare Pages: FastAPI
// работает прямо в браузере (src/browser-backend), сервер не нужен.
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
    // Браузерная версия берёт Python-код из ../api и ../storage.
    fs: { allow: ['..'] },
  },
  worker: { format: 'es' },
  build: {
    // Без сообщений о том, сколько времени заняли плагины: это не ошибка.
    rolldownOptions: { checks: { bundlerTimings: false } },
  },
  test: {
    environment: 'node',
  },
})
