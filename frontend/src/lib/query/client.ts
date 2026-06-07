"use client";

import { QueryClient } from "@tanstack/react-query";

/**
 * QueryClient 单例 —— 在 Providers 注入
 *
 * - staleTime 30s:避免每次组件 mount 都重拉
 * - retry 1:网络抖动重试一次,失败暴露给 UI
 * - refetchOnWindowFocus 关:Dashboard 数据不需要每次切窗都打后端
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}
