import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    hmr: { host: 'localhost' },
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        timeout: 600000,  // 10分钟 — 大视频上传不超时
      },
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  },
})
