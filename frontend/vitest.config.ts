import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import path from "node:path";

/**
 * Vitest 配置 —— 组件测试 + 纯函数测试共用
 *
 * - jsdom 环境跑组件(需 React testing-library)
 * - @/ 别名跟 tsconfig 一致
 * - 覆盖率用 v8,排除 tests/ 和 *.d.ts
 */
const root = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      exclude: ["tests/**", "**/*.d.ts", "**/index.ts"],
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(root, "src"),
    },
  },
});
