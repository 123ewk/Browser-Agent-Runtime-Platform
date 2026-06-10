"use client";

import { Pause, Play, StopCircle, AlertCircle } from "lucide-react";
import { useState } from "react";
import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";
import { useTask, usePauseTask, useResumeTask, useStopTask } from "@/lib/query/tasks";
import type { TaskStatus } from "@/types/task";

/**
 * 任务控制条 —— 第三个逃生通道(2026-06-10 新增)
 *
 * 三个动作:
 * - 停止:任何非终态 → STOPPING → CANCELLED,Worker 退出
 * - 暂停:RUNNING/WAITING_CONFIRM → PAUSED,V1 Worker 退出
 * - 继续:PAUSED → RUNNING,V1 仅恢复状态机
 *
 * 可见性规则(对应状态白名单):
 * - running / waiting_confirm / pending: 显示「暂停」「停止」
 * - paused: 显示「继续」「停止」
 * - stopping(中间态): 显示「停止中…」disabled
 * - 终态(completed/failed/cancelled): 不显示整个条
 *
 * 错误展示:
 * - 后端 accepted=false(reason 不为空)显示在条下方,半透明
 * - 网络/HTTP 错误通过 mutation.error 捕获
 */
const ACTIONABLE_STATUSES: ReadonlySet<TaskStatus> = new Set<TaskStatus>([
  "pending",
  "running",
  "waiting_confirm",
  "paused",
  "stopping",
]);

const TERMINAL_STATUSES: ReadonlySet<TaskStatus> = new Set<TaskStatus>([
  "completed",
  "failed",
  "cancelled",
]);

export function TaskControlBar(): React.ReactElement | null {
  const activeId = useAgentWorkspaceStore((s) => s.activeTaskId);
  const { data: taskDetail } = useTask(activeId);
  const taskStatus = taskDetail?.status as TaskStatus | undefined;

  const stopMut = useStopTask();
  const pauseMut = usePauseTask();
  const resumeMut = useResumeTask();

  // 防止连点:本地 busy 锁
  const [localBusy, setLocalBusy] = useState<"stop" | "pause" | "resume" | null>(
    null,
  );

  if (!activeId || !taskStatus) return null;
  if (TERMINAL_STATUSES.has(taskStatus)) return null;
  if (!ACTIONABLE_STATUSES.has(taskStatus)) return null;

  const anyPending =
    stopMut.isPending || pauseMut.isPending || resumeMut.isPending;

  const onStop = (): void => {
    if (anyPending || localBusy !== null) return;
    setLocalBusy("stop");
    stopMut.mutate(activeId, {
      onSettled: () => setLocalBusy(null),
    });
  };
  const onPause = (): void => {
    if (anyPending || localBusy !== null) return;
    setLocalBusy("pause");
    pauseMut.mutate(activeId, {
      onSettled: () => setLocalBusy(null),
    });
  };
  const onResume = (): void => {
    if (anyPending || localBusy !== null) return;
    setLocalBusy("resume");
    resumeMut.mutate(activeId, {
      onSettled: () => setLocalBusy(null),
    });
  };

  // 错误信息(优先级: 网络/HTTP 错误 > 后端 accepted=false 的 reason)
  const errorMessage =
    stopMut.error?.message ??
    pauseMut.error?.message ??
    resumeMut.error?.message ??
    null;

  // 后端拒绝(reason 非空但 accepted=false):展示轻提示
  const lastReason =
    stopMut.data && !stopMut.data.accepted
      ? stopMut.data.reason
      : pauseMut.data && !pauseMut.data.accepted
        ? pauseMut.data.reason
        : resumeMut.data && !resumeMut.data.accepted
          ? resumeMut.data.reason
          : null;

  return (
    <div className="flex flex-col gap-1 border-b border-outline-variant bg-surface-container-lowest px-4 py-2">
      <div className="flex items-center justify-end gap-2">
        {/* 暂停/继续 互斥显示 */}
        {taskStatus === "paused" ? (
          <button
            type="button"
            onClick={onResume}
            disabled={anyPending || localBusy !== null}
            title="继续任务(状态机恢复,Worker 续跑需 V2 Checkpoint 协议)"
            className="inline-flex items-center gap-1 rounded-md border border-outline-variant bg-surface-container-lowest px-2.5 py-1 text-xs font-medium text-on-surface transition-colors hover:bg-primary-container/20 hover:text-primary hover:border-primary-container/40 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Play size={12} />
            继续
          </button>
        ) : (
          <button
            type="button"
            onClick={onPause}
            disabled={anyPending || localBusy !== null || taskStatus === "stopping"}
            title="暂停任务(状态转 PAUSED,V1 Worker 退出)"
            className="inline-flex items-center gap-1 rounded-md border border-outline-variant bg-surface-container-lowest px-2.5 py-1 text-xs font-medium text-on-surface transition-colors hover:bg-primary-container/20 hover:text-primary hover:border-primary-container/40 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Pause size={12} />
            暂停
          </button>
        )}

        <button
          type="button"
          onClick={onStop}
          disabled={anyPending || localBusy !== null || taskStatus === "stopping"}
          title="停止任务(转 CANCELLED,Worker 退出,不可恢复)"
          className="inline-flex items-center gap-1 rounded-md border border-error/40 bg-surface-container-lowest px-2.5 py-1 text-xs font-medium text-error transition-colors hover:bg-error-container/40 hover:border-error/60 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <StopCircle size={12} />
          {taskStatus === "stopping" ? "停止中…" : "停止"}
        </button>
      </div>

      {(errorMessage !== null || lastReason !== null) && (
        <div className="flex items-center justify-end gap-1 text-[11px] text-on-surface-variant/80">
          <AlertCircle size={11} />
          <span>{errorMessage ?? lastReason}</span>
        </div>
      )}
    </div>
  );
}
