"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getTaskTimeline,
  postTaskMessage,
} from "@/lib/api/timeline";
import { queryKeys } from "./keys";

/** Timeline 拉取 —— 高频轮询(5s),与 WS 推送互为兜底 */
export function useTaskTimeline(taskId: string | null) {
  return useQuery({
    queryKey: taskId ? queryKeys.timeline.byTask(taskId) : ["timeline", "idle"],
    queryFn: () => getTaskTimeline(taskId as string),
    enabled: Boolean(taskId),
    refetchInterval: 5_000,
  });
}

/** 发送指令 —— 成功后 invalidate task detail,触发 UI 刷新 */
export function useSendMessage(taskId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { content: string; runMode: "yolo" | "semi" }) =>
      postTaskMessage(taskId, vars.content, vars.runMode),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) });
    },
  });
}
