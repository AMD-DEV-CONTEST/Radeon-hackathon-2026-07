import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      // Proxy API calls to local backend during development
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        ws: true, // WebSocket support for streaming
      },
    },
  },
})
