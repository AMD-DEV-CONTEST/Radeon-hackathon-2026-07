import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  // 钉死 Turbopack 工作区根目录为项目目录。
  // 主目录存在残留的 lockfile（~/package-lock.json、~/pnpm-lock.yaml），
  // 会导致 Next 误把整个 HOME 推断为 workspace root，文件监听范围失控、内存爆掉。
  turbopack: { root: path.join(__dirname) },
  async headers() {
    return [
      {
        source: "/chatIndex",
        headers: [
          { key: "Cache-Control", value: "no-store" },
          { key: "X-H5-Deployment", value: "dify-h5-v1" },
        ],
      },
      {
        source: "/api/v1/9808/conring/robot/chat",
        headers: [
          { key: "Cache-Control", value: "no-store" },
          { key: "X-H5-Deployment", value: "dify-h5-v1" },
        ],
      },
      {
        source: "/v1/chat-messages",
        headers: [
          { key: "Cache-Control", value: "no-store" },
          { key: "X-H5-Deployment", value: "dify-h5-v1" },
        ],
      },
    ];
  },
};

export default nextConfig;
