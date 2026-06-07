"use client";

import { useQuery } from "@tanstack/react-query";
import { getTask, listTasks, type ListTasksParams } from "@/lib/api/tasks";
import { queryKeys } from "./keys";

/** 任务列表查询 —— 任务中心 / Dashboard 最近任务共用 */
export function useTasks(params: ListTasksParams = {}) {
  return useQuery({
    queryKey: queryKeys.tasks.list(params),
    queryFn: () => listTasks(params),
  });
}

/** 单个任务详情 —— Workspace / Task Detail 共用 */
export function useTask(id: string | null) {
  return useQuery({
    queryKey: id ? queryKeys.tasks.detail(id) : ["task", "idle"],
    queryFn: () => getTask(id as string),
    enabled: Boolean(id),
  });
}
