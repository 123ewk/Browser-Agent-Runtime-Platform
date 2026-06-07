import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * 合并 Tailwind className —— 处理冲突(后写覆盖先写)
 *
 * 这是项目里**唯一**的"通用工具函数",因为 shadcn/ui 生态强依赖它。
 * 其他工具函数按职责拆到 `lib/format/*`、`lib/api/*` 等具体模块。
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
