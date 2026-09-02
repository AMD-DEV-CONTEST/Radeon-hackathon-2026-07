import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // The browser talks to the Vite origin in development. Keep the API on
    // localhost in the cloud instance and proxy same-origin `/api` requests
    // to FastAPI, avoiding an exposed API port and CORS configuration drift.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:9000',
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'node',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    // Avoid the tinypool worker teardown hang/OOM seen on Node 25 (Windows):
    // run tests in the main process instead of spawning worker threads/forks.
    isolate: false,
    fileParallelism: false,
  },
})
