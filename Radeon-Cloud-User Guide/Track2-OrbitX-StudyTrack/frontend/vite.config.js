import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiProxyTarget = process.env.VITE_API_URL

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts: true,
    proxy: apiProxyTarget ? {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
        secure: false
      }
    } : undefined
  }
})
