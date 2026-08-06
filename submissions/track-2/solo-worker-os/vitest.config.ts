import { defineConfig } from 'vitest/config';
import path from 'node:path';

// vitest 配置：
// - resolve.alias 将 `@/` 映射到项目根目录，与 tsconfig.json 的 paths 保持一致
// - test.environment 默认使用 node（三个核心测试均为后端纯逻辑），
//   后续 React 组件测试可在文件顶部用 `// @vitest-environment jsdom` 切换
// - test.include 仅匹配 tests/ 目录下的 .test.ts 文件
export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './'),
    },
  },
  test: {
    environment: 'node',
    include: ['tests/**/*.test.ts'],
    globals: true,
  },
});
