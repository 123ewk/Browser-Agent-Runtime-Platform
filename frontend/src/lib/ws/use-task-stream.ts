"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { subscribeTaskStream } from "./task-stream";
import { queryKeys } from "@/lib/query/keys";
import type { RuntimeEvent } from "@/types/chat";

/**
 * 把任务实时流绑到 TanStack Query 缓存
 *
 * - 收到 step/screenshot 事件时, 失效 tasks 域所有查询(列表 + detail)
 *   之所以用 tasks.all 而不是单点 invalidate:
 *     1) 列表 key 带分页/搜索参数, 单点失效容易漏
 *     2) 当前激活的 task detail 必须失效(用户在看详情页)
 *     3) 失效开销只是触发 refetch, 不会发业务命令, 完全可以宽打
 * - 状态切换(完成/失败/取消)同走 tasks.all, 列表卡片 status 才能实时切
 * - 单一职责: 本 hook 只管"事件 → 缓存失效", 不做 UI 订阅
 *
 * 2026-06-10 bug 修复: 原实现只 invalidate detail, 列表 status 永远不更新
 * 详见 docs/issues/2026-06-10-task-status-stuck-pending.md §6.1
 */
export function useTaskStreamInvalidation(taskId: string | null): void {
  const qc = useQueryClient();
  useEffect(() => {
    if (!taskId) return;
    const off = subscribeTaskStream(taskId, () => {
      // 宽失效: 列表 + detail 都重新拉, status 才会动态变
      qc.invalidateQueries({ queryKey: queryKeys.tasks.all });
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
        // 事件入口做幂等 —— 把"重复 / 残缺事件"的脏数据挡在 state 之外
        // 触发场景: WS 断线重连后,后端把累积事件按原 event_id 重推;
        //          或 try/catch 解析分支漏掉 event_id 字段缺失的半条消息。
        // 这两类都会让下游 Timeline 的 <TimelineStepRow key={e.event_id}> 报 unique-key 警告。
        setEvents((prev) => {
          // 防御 1: 缺 event_id 视为非法事件,丢弃(零信任:不依赖后端一定填)
          if (!event.event_id) {
            return prev;
          }
          // 防御 2: 同一 event_id 已存在则跳过(断线重连重推去重)
          if (prev.some((p) => p.event_id === event.event_id)) {
            return prev;
          }
          return [...prev, event];
        });
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
