"use client";

import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";
import { useCreateTask, useTask } from "@/lib/query/tasks";

/**
 * 提交逻辑 hook —— 封装 disabled 计算 + 草稿发送
 *
 * 无活动任务 → 创建新任务(goal = 用户输入)
 * 有活动任务且正在执行 → disabled
 * 有活动任务且已结束 → 可创建下一个任务
 */
export function useChatSubmit(): {
  readonly disabled: boolean;
  readonly onSend: () => void;
} {
  const activeId = useAgentWorkspaceStore((s) => s.activeTaskId);
  const draft = useAgentWorkspaceStore((s) => s.draft);
  const clearDraft = useAgentWorkspaceStore((s) => s.clearDraft);
  const setActiveTaskId = useAgentWorkspaceStore((s) => s.setActiveTaskId);

  const createTask = useCreateTask();
  const { data: currentTask } = useTask(activeId);

  // 判断当前任务是否还在执行中(非终态 + 数据已加载)
  // 终态参考后端 TaskState: completed / failed / cancelled
  // 半自动模式还可能停在 waiting_confirm / paused / stopping,这些都不允许创建新任务
  const taskStatus = currentTask?.status;
  const isActive = taskStatus !== undefined && taskStatus !== "completed" && taskStatus !== "failed" && taskStatus !== "cancelled";

  // disabled 条件:
  //   - 正在提交创建中
  //   - 有 activeId 但任务数据尚未加载(刚创建/切换)
  //   - 有 activeId 且任务仍在执行(非终态)
  const disabled =
    createTask.isPending ||
    (Boolean(activeId) && (isActive || !taskStatus));

  const onSend = (): void => {
    if (draft.trim() === "") return;
    if (activeId && isActive) return; // 未结束的任务不允许创建新任务

    const goal = draft.trim();
    createTask.mutate(goal, {
      onSuccess: (response) => {
        setActiveTaskId(response.task_id);
        clearDraft();
      },
    });
  };

  return { disabled, onSend };
}
