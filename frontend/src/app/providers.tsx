"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState, type ReactNode } from "react";
import { createQueryClient } from "@/lib/query/client";

/**
 * 全局 Provider 注入 —— QueryClient + Theme
 *
 * - QueryClient 用 useState 包裹:避免每次 re-render 重建客户端
 *   (重建会丢缓存,导致 refetch 风暴)
 * - Theme 默认跟随系统,支持 light/dark/system 三档
 */
export function Providers({ children }: { readonly children: ReactNode }) {
  const [queryClient] = useState(() => createQueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider
        attribute="class"
        defaultTheme="system"
        enableSystem
        disableTransitionOnChange
      >
        {children}
      </ThemeProvider>
    </QueryClientProvider>
  );
}
