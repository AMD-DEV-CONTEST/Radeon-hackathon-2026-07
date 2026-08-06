import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    host: true,
    // 允许隧道等外部域名访问（dev 模式默认拦截未知 Host）
    allowedHosts: true,
    proxy: {
      // 开发环境代理到 FastAPI；生产构建由 FastAPI 同源托管
      '/api': 'http://127.0.0.1:8510',
    },
  },
})
