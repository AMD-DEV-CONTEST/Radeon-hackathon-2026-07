import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { readFileSync } from "node:fs";

const host = process.env.TAURI_DEV_HOST;
const devApiUrl = process.env.AETHERDB_DEV_API_URL;
const tauriConfig = JSON.parse(readFileSync(new URL("./src-tauri/tauri.conf.json", import.meta.url), "utf8"));
const buildId = process.env.AETHERDB_BUILD_ID || `dev-${tauriConfig.version}`;

function localDevApiTarget(value) {
  if (!value) return null;
  const target = new URL(value);
  if (target.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(target.hostname) || !target.port) {
    throw new Error("AETHERDB_DEV_API_URL must be an explicit local HTTP endpoint with a dynamic port");
  }
  return target.origin;
}

const devApiTarget = localDevApiTarget(devApiUrl);

export default defineConfig({
  plugins: [vue()],
  define: {
    __APP_VERSION__: JSON.stringify(tauriConfig.version),
    __BUILD_ID__: JSON.stringify(buildId),
  },
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    watch: { ignored: ["**/src-tauri/**"] },
    proxy: devApiTarget ? {
      "/api": {
        target: devApiTarget,
        changeOrigin: true,
      },
    } : undefined,
  },
  envPrefix: ["VITE_", "TAURI_"],
  build: {
    outDir: "../dist/frontend",
    emptyOutDir: true,
    target: process.env.TAURI_ENV_PLATFORM === "windows" ? "chrome105" : "safari13",
    minify: !process.env.TAURI_ENV_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
  },
});
