import Link from "next/link";
import { MoreVertical } from "lucide-react";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { formatRelativeTime } from "@/lib/format/time";
import { formatUsd } from "@/lib/format/currency";
import type { TaskSummary } from "@/types/task";

/** 单行任务 —— 表格行,hover 高亮(zebra) */
export function RecentTaskRow({ task }: { readonly task: TaskSummary }) {
  return (
    <tr className="table-row-hover border-b border-outline-variant/60 transition-colors">
      <td className="px-4 py-3">
        <div className="truncate text-sm font-medium text-on-surface">
          {task.goal}
        </div>
        <div className="mt-0.5 text-[11px] text-on-surface-variant">
          {task.agentName}
        </div>
      </td>
      <td className="px-4 py-3">
        <StatusBadge status={task.status} />
      </td>
      <td className="px-4 py-3 text-sm text-on-surface-variant">
        {formatRelativeTime(task.createdAt)}
      </td>
      <td className="px-4 py-3 text-right font-mono text-sm text-on-surface">
        {task.costUsd > 0 ? formatUsd(task.costUsd) : "—"}
      </td>
      <td className="px-2 py-3 text-right">
        <Link
          href={`/tasks/${task.id}`}
          className="text-sm font-medium text-primary hover:underline"
        >
          详情
        </Link>
      </td>
      <td className="px-2 py-3 text-right">
        <button
          type="button"
          aria-label="更多操作"
          className="text-on-surface-variant hover:text-primary"
        >
          <MoreVertical className="h-4 w-4" />
        </button>
      </td>
    </tr>
  );
}
