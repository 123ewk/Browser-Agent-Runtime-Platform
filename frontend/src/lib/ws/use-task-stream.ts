"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { subscribeTaskStream } from "./task-stream";
import { queryKeys } from "@/lib/query/keys";
import type { RuntimeEvent } from "@/types/chat";

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

/**
 * 订阅任务事件流,直接返回事件数组用于 Timeline 渲染
 *
 * MVP 版本: 前端直接消费 WebSocket 事件,不走 TanStack Query 中间层。
 * 返回的事件列表按时间顺序追加,组件卸载时自动清理。
 */
export function useTaskStream(taskId: string | null): {
  events: RuntimeEvent[];
  isConnected: boolean;
} {
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    if (!taskId) {
      setEvents([]);
      setIsConnected(false);
      return;
    }

    // 切换 task 时重置
    setEvents([]);

    const off = subscribeTaskStream(
      taskId,
      (event) => {
        // 函数式更新: 基于最新 state 追加,避免闭包过期问题
        setEvents((prev) => [...prev, event]);
      },
      () => setIsConnected(true),   // onConnect: WebSocket 真正建立后才标记已连接
      () => setIsConnected(false),  // onDisconnect
    );

    return () => {
      off();
      setIsConnected(false);
    };
  }, [taskId]);

  return { events, isConnected };
}
