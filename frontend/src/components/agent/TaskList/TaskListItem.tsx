"use client";

import { StatusBadge } from "@/components/shared";
import { formatRelativeTime } from "@/lib/format/time";
import type { TaskSummary } from "@/types/task";

interface TaskListItemProps {
  readonly task: TaskSummary;
  readonly active: boolean;
  readonly onClick: () => void;
}

const BASE =
  "w-full rounded-md border p-3 text-left transition-colors";
const ACTIVE = "border-primary bg-primary-container/10";
const DEFAULT =
  "border-outline-variant bg-surface-container-lowest hover:bg-surface-container-low";

/** 单个任务卡片 —— 卡片式而非表格,贴合 AI 工作台"事件流"氛围 */
export function TaskListItem({
  task,
  active,
  onClick,
}: TaskListItemProps): React.ReactElement {
  const cls = `${BASE} ${active ? ACTIVE : DEFAULT}`;
  return (
    <li>
      <button type="button" onClick={onClick} className={cls}>
        <div className="flex items-center justify-between">
          <span className="font-mono text-xs text-on-surface-variant">
            {task.id}
          </span>
          <span className="text-xs text-on-surface-variant">
            {formatRelativeTime(task.updatedAt)}
          </span>
        </div>
        <p className="mt-1 line-clamp-2 text-sm text-on-surface">
          {task.goal}
        </p>
        <div className="mt-2 flex items-center justify-between">
          <span className="truncate text-xs text-on-surface-variant">
            {task.agentName}
          </span>
          <StatusBadge status={task.status} />
        </div>
      </button>
    </li>
  );
}
