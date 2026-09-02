import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { defineConfig } from "vitest/config";

import { amdPreviewGateway, developmentGateway } from "./gateway.config";

export default defineConfig({
  plugins: [
    react(),
    {
      name: "consumer-deployment-contract",
      resolveId(id) {
        return id === "virtual:consumer-nginx" ? "\0virtual:consumer-nginx" : undefined;
      },
      load(id) {
        if (id !== "\0virtual:consumer-nginx") return undefined;
        const config = readFileSync(new URL("../deploy/consumer-web-nginx.conf", import.meta.url), "utf8");
        return `export default ${JSON.stringify(config)}`;
      },
    },
  ],
  server: {
    ...developmentGateway,
  },
  preview: {
    ...amdPreviewGateway,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
