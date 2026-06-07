import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@/styles/globals.css";
import { Providers } from "./providers";

/**
 * 根布局 —— 注入全局 Provider + 字体
 *
 * 字体:Inter + JetBrains Mono,跟 DESIGN.md 排版规则一致
 */
export const metadata: Metadata = {
  title: "AgenticFlow",
  description: "AI 编排控制台 —— Browser Agent Runtime Platform",
};

export default function RootLayout({
  children,
}: {
  readonly children: ReactNode;
}) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
        />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
