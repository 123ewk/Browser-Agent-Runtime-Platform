import type { NextConfig } from "next";

/**
 * Next.js 配置
 *
 * - 启用 React Strict Mode 捕获开发期副作用问题
 * - 配置 standalone 输出,方便后续 Docker 部署
 * - 不在 next.config 里写业务配置(API 地址走运行时环境变量)
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  // output: "standalone",  // Docker 部署时取消注释;Windows 下 pnpm symlink 不支持
  poweredByHeader: false,
  experimental: {
    typedRoutes: true,
  },
};

export default nextConfig;
