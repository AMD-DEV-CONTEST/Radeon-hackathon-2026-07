import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 本地 Vite 走 HTTP 代理（无 mixed-content 问题）。云端 Setup 才直连 https://localhost:8002。
// 本地开发请用: cd apps/realtime && python run_api.py --http
// 若本机 Agent 已切 HTTPS，可设 VITE_REALTIME_PROXY=https://127.0.0.1:8002
const REALTIME = process.env.VITE_REALTIME_PROXY || 'http://127.0.0.1:8002'
const REALTIME_WS = REALTIME.replace(/^http/, 'ws')

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('three') || id.includes('@react-three')) return 'three-vendor'
          if (id.includes('@xyflow')) return 'workflow-vendor'
          if (id.includes('react-router') || id.includes('react-dom') || id.includes('/react/')) {
            return 'react-vendor'
          }
        },
      },
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      // 业务 API -> apps/api (:8000)
      '/api/v1': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // URDF / 实时录制控制 -> apps/realtime (:8002)
      '/api/urdf': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      '/api/record': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      '/api/status': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // M2: 数据集只读镜像 + 回放 meta -> apps/realtime
      '/api/datasets': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      '/api/playback': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // M3: 本地模型列表 + compare meta -> apps/realtime
      '/api/inference': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // M6: runtime 元数据 -> apps/realtime
      '/api/runtimes': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // Config-driven robot platform API -> apps/realtime
      '/api/robots': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // HuggingFace token probe used by setup Step 4 -> apps/realtime
      '/api/hf': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // M8: camera streaming -> apps/realtime
      '/api/camera': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // M8.3: vision-conditioned inference -> apps/realtime
      '/api/vision_inference': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // M9.1: realtime-side preflight (ports scan / wiggle / health) -> apps/realtime
      '/api/setup': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // M16: calibration control -> apps/realtime
      '/api/calibrate': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // Reachy Mini daemon proxy -> apps/realtime (:8002)
      '/api/reachy': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // M9.2 Step 3: inline teleop start/stop/status -> apps/realtime
      '/api/teleop': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // M27: B601-RS control -> apps/realtime
      '/api/b601': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
        timeout: 180_000,
        proxyTimeout: 180_000,
      },
      // LeKiwi mobile manipulator host/client + dataset loop -> realtime
      '/api/lekiwi': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
        timeout: 180_000,
        proxyTimeout: 180_000,
      },
      // Quest WebXR teleoperation sessions -> realtime
      '/api/quest_teleop': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // User-configurable GPU/SSH compute nodes -> realtime
      '/api/remote_compute': {
        target: REALTIME,
        changeOrigin: true,
        secure: false,
      },
      // 兜底: 未匹配的 /api/* 全部转发到 apps/api (:8000)
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // M3: training 进度 WS -> apps/api (:8000). 放在 /ws 之前.
      '/ws/trainings': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
      // WebSocket 默认 -> apps/realtime (:8002): teleop, ui, playback, compare, ...
      '/ws': {
        target: REALTIME_WS,
        ws: true,
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
