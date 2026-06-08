"use client";

import type { RuntimeEvent } from "@/types/chat";
import { stepKindMeta } from "./step-kind-meta";

interface TimelineStepRowProps {
  readonly event: RuntimeEvent;
}

/** 格式化 ISO 时间为 HH:MM:SS */
function formatTime(isoTs: string): string {
  const d = new Date(isoTs);
  return d.toLocaleTimeString("zh-CN", { hour12: false });
}

/** 从 payload 提取人类可读的摘要 */
function pickSummary(event: RuntimeEvent): string {
  const p = event.payload;

  switch (event.event) {
    case "STEP_START":
      return `${p.action ?? ""} — ${p.description ?? ""}`;
    case "STEP_COMPLETE":
      return p.summary ?? "";
    case "SCREENSHOT":
      return `截图已保存: ${p.file_key ?? ""}`;
    case "ERROR":
      return `[${p.error_type ?? "ERROR"}] ${p.message ?? ""}`;
    case "TASK_FINISHED":
      return `${p.summary ?? ""} (共 ${p.total_steps ?? 0} 步)`;
    case "NEED_CONFIRM":
      return `${p.question ?? ""} [${p.severity ?? "medium"}]`;
    case "PROGRESS":
      return `${p.current ?? 0} / ${p.total ?? 0}`;
    case "TASK_STATE_CHANGED":
      return `${p.from_state ?? "?"} → ${p.to_state ?? "?"}: ${p.reason ?? ""}`;
    case "WORKER_READY":
      return "Worker 进程已就绪";
    case "COMMAND_ACK":
      return "命令已确认";
    default:
      return "";
  }
}

export function TimelineStepRow({
  event,
}: TimelineStepRowProps): React.ReactElement {
  const { Icon, tone, label } = stepKindMeta[event.event] ?? stepKindMeta.ERROR;
  const summary = pickSummary(event);

  return (
    <li className="flex gap-3">
      <div
        className={[
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
          tone,
        ].join(" ")}
      >
        <Icon size={14} />
      </div>
      <div className="flex-1 rounded-md border border-outline-variant bg-surface-container-lowest p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-on-surface">{label}</span>
          <span className="font-mono text-xs text-on-surface-variant">
            {formatTime(event.ts)}
          </span>
        </div>
        {summary && (
          <p className="mt-1 text-sm text-on-surface-variant">{summary}</p>
        )}
      </div>
    </li>
  );
}
