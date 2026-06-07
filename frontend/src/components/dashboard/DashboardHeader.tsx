"use client";

import { Calendar } from "lucide-react";

/** Dashboard 头部 —— 标题 + 描述 + 时间范围(占位按钮,后续接 picker) */
export function DashboardHeader() {
  return (
    <div className="flex items-end justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-on-background">
          概览
        </h1>
        <p className="mt-1 text-sm text-on-surface-variant">
          监控代理性能和任务执行
        </p>
      </div>
      <button
        type="button"
        className="flex items-center gap-2 rounded border border-outline-variant bg-surface-container-lowest px-3 py-1.5 text-sm font-medium text-on-surface transition-colors hover:bg-surface-container-low"
      >
        <Calendar className="h-4 w-4" />
        今日
      </button>
    </div>
  );
}
