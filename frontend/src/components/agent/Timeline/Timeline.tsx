"use client";

import { useTaskTimeline } from "@/lib/query/timeline";
import { useTaskStreamInvalidation } from "@/lib/ws/use-task-stream";
import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";
import { TimelineHeader } from "./TimelineHeader";
import { TimelineStepRow } from "./TimelineStepRow";

/**
 * 中栏:Agent 执行时间轴
 *
 * 数据源: TanStack Query 拉取 + 5s 轮询,WebSocket 推事件时触发 invalidate
 * 行为: 未选中任务时显示空态引导;加载/错误三态内联处理
 */
export function Timeline(): React.ReactElement {
  const activeId = useAgentWorkspaceStore((s) => s.activeTaskId);
  useTaskStreamInvalidation(activeId);
  const { data, isLoading, isError } = useTaskTimeline(activeId);

  if (!activeId) {
    return (
      <div className="flex h-full flex-col">
        <TimelineHeader tokens={0} />
        <div className="flex flex-1 items-center justify-center p-6 text-sm text-on-surface-variant">
          请从左侧选择一个任务,查看 Agent 执行时间轴
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <TimelineHeader tokens={data?.reduce((sum, s) => sum + s.tokens, 0) ?? 0} />
      <div className="flex-1 overflow-y-auto p-4">
        {isLoading && (
          <div className="text-sm text-on-surface-variant">加载步骤中…</div>
        )}
        {isError && (
          <div className="text-sm text-error">步骤流加载失败</div>
        )}
        {data && data.length === 0 && (
          <div className="text-sm text-on-surface-variant">还没有步骤</div>
        )}
        <ol className="flex flex-col gap-3">
          {(data ?? []).map((s) => (
            <TimelineStepRow key={s.id} step={s} />
          ))}
        </ol>
      </div>
    </div>
  );
}
