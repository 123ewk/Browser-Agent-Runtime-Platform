import { cn } from "@/lib/cn";
import type { TaskStatus } from "@/types/task";

const STATUS_STYLES: Record<
  TaskStatus,
  { label: string; labelCn: string; dot: string; container: string; animate: boolean }
> = {
  pending: {
    label: "Pending",
    labelCn: "等待中",
    dot: "bg-on-surface-variant",
    container: "bg-surface-container text-on-surface-variant",
    animate: false,
  },
  running: {
    label: "Running",
    labelCn: "运行中",
    dot: "bg-primary",
    container:
      "bg-primary-container/20 text-primary border border-primary-container/30",
    animate: true,
  },
  awaiting_human: {
    label: "Awaiting",
    labelCn: "需介入",
    dot: "bg-tertiary",
    container:
      "bg-tertiary-container text-on-tertiary-container border border-tertiary-container",
    animate: true,
  },
  success: {
    label: "Success",
    labelCn: "成功",
    dot: "bg-secondary",
    container:
      "bg-secondary-container/30 text-secondary border border-secondary-container",
    animate: false,
  },
  failed: {
    label: "Failed",
    labelCn: "失败",
    dot: "bg-error",
    container: "bg-error-container text-on-error-container border border-error-container",
    animate: false,
  },
  cancelled: {
    label: "Cancelled",
    labelCn: "已取消",
    dot: "bg-on-surface-variant",
    container: "bg-surface-container text-on-surface-variant",
    animate: false,
  },
};

/** 任务状态徽章 —— capsule 形态(全圆角),与 DESIGN.md 一致 */
export function StatusBadge({
  status,
  lang = "cn",
  className,
}: {
  readonly status: TaskStatus;
  readonly lang?: "en" | "cn";
  readonly className?: string;
}) {
  const s = STATUS_STYLES[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold",
        s.container,
        className,
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          s.dot,
          s.animate && "animate-pulse",
        )}
      />
      {lang === "cn" ? s.labelCn : s.label}
    </span>
  );
}
