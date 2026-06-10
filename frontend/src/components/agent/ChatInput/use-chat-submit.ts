"use client";

import { useState } from "react";
import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";
import { useCreateTask, useTask } from "@/lib/query/tasks";
import { toApiError } from "@/lib/api/client";
import type { TaskStatus } from "@/types/task";

/**
 * 提交逻辑 hook —— 封装 disabled 计算 + 草稿发送 + 错误反馈
 *
 * 无活动任务 → 创建新任务(goal = 用户输入)
 * 有活动任务且正在执行 → disabled
 * 有活动任务且已结束 / 加载中 / 加载失败 → 可创建下一个任务
 *
 * 关键变更(2026-06-10 bug 修复):
 * 旧版用「非终态 = 在跑」黑名单,导致"pending" / "unknown" / 加载中 / API 失败
 * 都会锁死输入框。改为白名单:只在 taskStatus 明确属于"在跑"集合时才锁。
 *
 * 「在跑」集合与后端 TaskState 枚举对齐:
 *   running / waiting_confirm / paused / stopping
 *   (PENDING 不在内 —— 后端进入 PENDING 后下一步必然 RUNNING,且 PENDING
 *   常因重启/重连后短暂出现,锁上会让用户误以为"任务在跑")
 */
const RUNNING_STATUSES: ReadonlySet<TaskStatus> = new Set<TaskStatus>([
  "running",
  "waiting_confirm",
  "paused",
  "stopping",
]);

export function useChatSubmit(): {
  readonly disabled: boolean;
  readonly isPending: boolean;
  readonly error: string | null;
  readonly onSend: () => void;
  readonly clearError: () => void;
} {
  const activeId = useAgentWorkspaceStore((s) => s.activeTaskId);
  const draft = useAgentWorkspaceStore((s) => s.draft);
  const clearDraft = useAgentWorkspaceStore((s) => s.clearDraft);
  const setActiveTaskId = useAgentWorkspaceStore((s) => s.setActiveTaskId);

  const createTask = useCreateTask();
  const { data: currentTask } = useTask(activeId);

  const [error, setError] = useState<string | null>(null);

  // 白名单判定:只对"明确在跑"的 4 个状态锁输入。
  // taskStatus 是 undefined(加载中)/ null / "" / "pending" / 任何非法值都视为"可新建"。
  const taskStatus = currentTask?.status as TaskStatus | undefined;
  const isActive = taskStatus !== undefined && RUNNING_STATUSES.has(taskStatus);

  // disabled 条件:
  //   - 正在提交创建中
  //   - 有 activeId 且任务正在跑(白名单 4 个状态)
  // 注意:不再用「!taskStatus」条件,API 失败 / 数据未就绪都放行
  // (配合 AgentWorkspace 顶部的「+ 新建任务」逃生通道,用户随时能切到新输入态)
  const disabled = createTask.isPending || (Boolean(activeId) && isActive);

  const clearError = (): void => setError(null);

  const onSend = (): void => {
    clearError();

    // 前端参数校验: 空内容阻止提交
    if (draft.trim() === "") {
      setError("请输入任务目标,例如「打开百度搜索 Python」");
      return;
    }

    // 前端参数校验: 超长内容阻止提交(对齐后端 TaskCreate.goal max_length=2000)
    if (draft.trim().length > 2000) {
      setError(`任务描述过长(${draft.trim().length}/2000 字符),请精简后重试`);
      return;
    }

    if (activeId && isActive) return; // 未结束的任务不允许创建新任务

    const goal = draft.trim();
    createTask.mutate(goal, {
      onSuccess: (response) => {
        setActiveTaskId(response.task_id);
        clearDraft();
        clearError();
      },
      onError: (err) => {
        setError(toApiError(err).message);
      },
    });
  };

  return { disabled, isPending: createTask.isPending, error, onSend, clearError };
}
