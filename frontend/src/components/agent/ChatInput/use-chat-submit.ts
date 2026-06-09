"use client";

import { useState } from "react";
import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";
import { useCreateTask, useTask } from "@/lib/query/tasks";
import { toApiError } from "@/lib/api/client";

/**
 * 提交逻辑 hook —— 封装 disabled 计算 + 草稿发送 + 错误反馈
 *
 * 无活动任务 → 创建新任务(goal = 用户输入)
 * 有活动任务且正在执行 → disabled
 * 有活动任务且已结束 → 可创建下一个任务
 */
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

  // 判断当前任务是否还在执行中(非终态 + 数据已加载)
  const taskStatus = currentTask?.status;
  const isActive =
    taskStatus !== undefined &&
    taskStatus !== "completed" &&
    taskStatus !== "failed" &&
    taskStatus !== "cancelled";

  // disabled 条件:
  //   - 正在提交创建中
  //   - 有 activeId 但任务数据尚未加载(刚创建/切换)
  //   - 有 activeId 且任务仍在执行(非终态)
  const disabled =
    createTask.isPending ||
    (Boolean(activeId) && (isActive || !taskStatus));

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
