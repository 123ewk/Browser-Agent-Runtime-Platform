import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Inter, JetBrains_Mono, Material_Symbols_Outlined } from "next/font/google";
import "@/styles/globals.css";
import { Providers } from "./providers";
import { cn } from "@/lib/cn";

/**
 * 根布局 —— 注入全局 Provider + 字体
 *
 * 字体加载策略(Next.js 14+ App Router 最佳实践):
 * - 使用 next/font/google 而非 <link href="...">
 *   原因:next/font 会自动 self-host 字体、preload、自动避免 CLS
 * - 通过 className 把字体挂到 <html> 上,CSS 变量(--font-*) 给子组件用
 * - 三个字体:Inter(正文) + JetBrains Mono(代码/标签) + Material Symbols(品牌图标)
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

const materialSymbols = Material_Symbols_Outlined({
  weight: ["400", "500"],
  style: ["normal"],
  variable: "--font-material-symbols",
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
      className={cn(inter.variable, jetbrainsMono.variable, materialSymbols.variable)}
    >
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
