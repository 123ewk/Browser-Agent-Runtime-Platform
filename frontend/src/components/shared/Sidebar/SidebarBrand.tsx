import { Bot } from "lucide-react";
import { cn } from "@/lib/cn";

/**
 * 品牌标识 —— 顶部的 logo + 标题
 *
 * Sidebar 在桌面/移动端共用,品牌区视觉权重最高,放在最顶。
 */
export function SidebarBrand() {
  return (
    <div className="flex items-center gap-3 px-4 py-1">
      <div
        className={cn(
          "flex h-8 w-8 items-center justify-center rounded",
          "bg-primary-container text-on-primary-container",
        )}
      >
        <Bot className="h-5 w-5" />
      </div>
      <div>
        <div className="text-base font-bold leading-tight text-primary">
          AgenticFlow
        </div>
        <div className="text-[11px] font-medium leading-tight text-on-surface-variant">
          AI Orchestrator
        </div>
      </div>
    </div>
  );
}
