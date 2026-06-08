import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Inter, JetBrains_Mono } from "next/font/google";
import "@/styles/globals.css";
import { Providers } from "./providers";
import { cn } from "@/lib/cn";

/**
 * 根布局 —— 注入全局 Provider + 字体
 *
 * 字体加载策略(Next.js 14+ App Router 最佳实践):
 * - 文本字体(Inter / JetBrains Mono)走 next/font/google:
 *   自动 self-host、preload、避免 CLS,通过 CSS 变量(--font-*) 暴露给子组件
 * - Material Symbols 是 icon font(变体字体),不走 next/font/google:
 *   next/font 对 icon font 的 catalog 收录不全,Google 官方也是 <link> 加载,
 *   icon font 本来也不需要 self-host / preload 优化
 */
const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

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
    <html
      lang="zh-CN"
      suppressHydrationWarning
      className={cn(inter.variable, jetbrainsMono.variable)}
    >
      <head>
        {/*
          Material Symbols Outlined —— 用 <link> 加载而非 next/font/google
          原因见顶部"字体加载策略"注释
        */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=block"
        />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
