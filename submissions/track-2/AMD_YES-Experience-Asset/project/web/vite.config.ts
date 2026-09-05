/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Local-only by default. The dev server binds to 127.0.0.1 to match the
// repository rule that private services are not exposed to the network.
//
// Live mode talks to the FastAPI backend SAME-ORIGIN via a `/api` proxy, so the
// browser never makes a cross-origin request (no CORS needed) and the backend
// stays bound to loopback. Point the proxy at a running backend with
// VITE_PROXY_TARGET (default http://127.0.0.1:8080).
const DEFAULT_PROXY_TARGET = 'http://127.0.0.1:8080';

export function resolveProxyTarget(rawTarget: string | undefined): string {
  const target = rawTarget || DEFAULT_PROXY_TARGET;
  let url: URL;
  try {
    url = new URL(target);
  } catch {
    throw new Error('VITE_PROXY_TARGET must be an absolute loopback HTTP(S) origin.');
  }

  const isLoopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  const isHttp = url.protocol === 'http:' || url.protocol === 'https:';
  const isOriginOnly =
    url.username === '' &&
    url.password === '' &&
    url.pathname === '/' &&
    url.search === '' &&
    url.hash === '';

  if (!isLoopback || !isHttp || !isOriginOnly) {
    throw new Error(
      'VITE_PROXY_TARGET must be a loopback HTTP(S) origin using localhost, 127.0.0.1, or ::1.',
    );
  }
  return url.origin;
}

const proxyTarget = resolveProxyTarget(process.env.VITE_PROXY_TARGET);
const proxy = {
  '/api': { target: proxyTarget, changeOrigin: true },
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy,
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    proxy,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}', 'vite.config.test.ts'],
    exclude: ['e2e/**', 'node_modules/**'],
    coverage: {
      reporter: ['text', 'json-summary'],
    },
  },
});
