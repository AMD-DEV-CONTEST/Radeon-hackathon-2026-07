import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev-only config: proxies the backend's NON-UNIFORM prefixes to the API
// target. Kept separate from `vite.config.ts` so the test runner (Vitest)
// does not start a proxy agent. Run with: `npm run dev`.
// The FastAPI application listens on 9000 by default.  Keep the development
// proxy aligned with `.env.example` so a UI-only startup does not accidentally
// target the llama.cpp chat endpoint on 8000.
// Use the IPv4 loopback explicitly. Some Linux images resolve `localhost` to
// IPv6 first while the API deliberately binds only to 127.0.0.1.
const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:9000'

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(process.env.npm_package_version || '0.1.0'),
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/auth': { target: API_TARGET, changeOrigin: true },
      '/projects': { target: API_TARGET, changeOrigin: true },
      '/notifications': { target: API_TARGET, changeOrigin: true },
      // UI-5 system-admin telemetry uses these non-/api route prefixes.
      '/monitor': { target: API_TARGET, changeOrigin: true },
      '/admin': { target: API_TARGET, changeOrigin: true },
    },
  },
})
