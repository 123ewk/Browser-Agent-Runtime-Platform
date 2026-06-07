"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { subscribeTaskStream } from "./task-stream";
import { queryKeys } from "@/lib/query/keys";

/**
 * 把任务实时流绑到 TanStack Query 缓存
 *
 * - 收到 step/screenshot 事件时,invalidate 对应 task 的 detail
 * - status 变更也走 invalidate,触发组件重新渲染
 * - 单一职责:本 hook 只管"事件 → 缓存失效",不做 UI 订阅
 */
export function useTaskStreamInvalidation(taskId: string | null): void {
  const qc = useQueryClient();
  useEffect(() => {
    if (!taskId) return;
    const off = subscribeTaskStream(taskId, () => {
      qc.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) });
    });
    return off;
  }, [taskId, qc]);
}
