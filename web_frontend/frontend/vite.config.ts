import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import UnoCSS from 'unocss/vite'
import { fileURLToPath, URL } from 'node:url'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    UnoCSS(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173, // Tauri expects frontend on 5173 by default
    strictPort: true, // Fail if port is already in use
    host: '127.0.0.1', // Bind to localhost for security
    proxy: {
      '/events': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    }
  },
  build: {
    target: 'esnext',
    minify: 'terser',
    rollupOptions: {
      input: {
        app: fileURLToPath(new URL('./index.html', import.meta.url)),
        showcase: fileURLToPath(new URL('./showcase.html', import.meta.url)),
      },
      output: {
        manualChunks: {
          'vue-vendor': ['vue', 'vue-router', 'pinia'],
          'ui-vendor': ['naive-ui'],
          'editor': ['monaco-editor'],
          'markdown': [
            'unified',
            'remark-parse',
            'remark-gfm',
            'remark-math',
            'remark-rehype',
            'rehype-highlight',
            'rehype-katex',
            'rehype-sanitize',
            'rehype-stringify',
            'unist-util-visit',
            'highlight.js',
            'katex',
            'mermaid',
          ]
        }
      }
    }
  }
})
