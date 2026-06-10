"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createTask,
  getTask,
  listTasks,
  pauseTask,
  resumeTask,
  stopTask,
  type ListTasksParams,
} from "@/lib/api/tasks";
import { queryKeys } from "./keys";

/** 任务列表查询 —— 任务中心 / Dashboard 最近任务共用
 *
 * 实时策略: WS 推送 + 5s 轮询兜底(C 方案, 详见
 * docs/issues/2026-06-10-task-status-stuck-pending.md §5)
 *
 * 选 5s 的理由:
 * - WS 正常时, status 切换 < 100ms, 轮询基本是空跑
 * - WS 失联(5 次 backoff 后)/ 后台标签页休眠, 5s 兜底保证最终一致
 * - 比 3s 少 40% 请求量, 比 10s 用户感知更及时
 *
 * `refetchIntervalInBackground: false`: 后台标签页停轮询,
 * 回到前台时 React Query 自动 refetch 一次补齐
 */
export function useTasks(params: ListTasksParams = {}) {
  return useQuery({
    queryKey: queryKeys.tasks.list(params),
    queryFn: () => listTasks(params),
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
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

/* ═══════════════════════════════════════════════════════════════
 * 任务控制 mutations —— 2026-06-10 新增(逃生通道)
 * ═══════════════════════════════════════════════════════════════
 *
 * 三个 mutation 都遵循同一模式:
 * 1. mutationFn 调用对应后端接口
 * 2. onSuccess 失效 task 详情 + 列表(状态变化可能影响两边)
 * 3. 失败不抛错给 UI 顶层 —— 各 hook 的调用方按需展示错误
 *
 * 为什么三个都用同一种结构(而非抽公共函数):
 * - 三个 mutation 数量很少,抽公共函数反而增加阅读成本
 * - 后续若要统一加埋点 / 错误处理,直接复制粘贴即可
 */

export function useStopTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => stopTask(taskId),
    onSuccess: (response) => {
      // 失效 detail(状态变了)+ 列表(列表里也会更新)
      qc.invalidateQueries({ queryKey: queryKeys.tasks.detail(response.task_id) });
      qc.invalidateQueries({ queryKey: queryKeys.tasks.all });
    },
  });
}

export function usePauseTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => pauseTask(taskId),
    onSuccess: (response) => {
      qc.invalidateQueries({ queryKey: queryKeys.tasks.detail(response.task_id) });
      qc.invalidateQueries({ queryKey: queryKeys.tasks.all });
    },
  });
}

export function useResumeTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => resumeTask(taskId),
    onSuccess: (response) => {
      qc.invalidateQueries({ queryKey: queryKeys.tasks.detail(response.task_id) });
      qc.invalidateQueries({ queryKey: queryKeys.tasks.all });
    },
  });
}
