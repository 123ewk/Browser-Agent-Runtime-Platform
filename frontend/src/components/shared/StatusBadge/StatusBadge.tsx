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
  waiting_confirm: {
    label: "Awaiting",
    labelCn: "需介入",
    dot: "bg-tertiary",
    container:
      "bg-tertiary-container text-on-tertiary-container border border-tertiary-container",
    animate: true,
  },
  paused: {
    label: "Paused",
    labelCn: "已暂停",
    dot: "bg-on-surface-variant",
    container: "bg-surface-container text-on-surface-variant",
    animate: true,
  },
  stopping: {
    label: "Stopping",
    labelCn: "停止中",
    dot: "bg-amber-500",
    container: "bg-surface-container text-on-surface-variant border border-amber-500/30",
    animate: true,
  },
  completed: {
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

/** 兜底样式 —— 后端新增 status 但前端尚未同步、或 status 为空值时使用 */
const UNKNOWN_STYLE = {
  label: "Unknown",
  labelCn: "未知",
  dot: "bg-on-surface-variant",
  container: "bg-surface-container text-on-surface-variant",
  animate: false,
} as const;

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
  // 防御性兜底:后端可能返回前端 STATUS_STYLES 尚未覆盖的 status(例如新增枚举)
  // 此时降级到 UNKNOWN_STYLE,避免组件崩溃阻塞整个列表渲染
  const s = STATUS_STYLES[status] ?? UNKNOWN_STYLE;
  if (!STATUS_STYLES[status] && status !== undefined) {
    // 上游数据漂移信号:warn 一次,方便定位后端协议与前端样式表的同步缺口
    console.warn(`[StatusBadge] 未识别的 status: ${String(status)}`);
  }
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
