"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createTask,
  getTask,
  listTasks,
  type ListTasksParams,
} from "@/lib/api/tasks";
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
    queryKey: id ? queryKeys.tasks.detail(id) : queryKeys.tasks.detail("idle"),
    queryFn: () => getTask(id as string),
    enabled: Boolean(id),
  });
}

/** 创建任务 —— 提交 goal 后自动失效列表缓存 */
export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (goal: string) => createTask(goal),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tasks.all });
    },
  });
}
