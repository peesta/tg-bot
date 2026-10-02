import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// В разработке (npm run dev) запросы /api уходят на FastAPI: python main.py
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  test: {
    environment: 'node',
  },
})
