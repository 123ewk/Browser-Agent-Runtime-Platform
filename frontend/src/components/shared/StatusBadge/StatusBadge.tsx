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

/** 加载中样式 —— status 还没返回(undefined / null / "")时的占位 */
const LOADING_STYLE = {
  label: "Loading",
  labelCn: "加载中",
  dot: "bg-on-surface-variant/50",
  container: "bg-surface-container text-on-surface-variant/70",
  animate: true,
} as const;

/** 任务状态徽章 —— capsule 形态(全圆角),与 DESIGN.md 一致

2026-06-10 改进:
- status 改为可选, undefined / null / "" 走 LOADING_STYLE(显示"加载中"而非"未知")
- 仅当 status 是 string 但不在 STATUS_STYLES 时才走 UNKNOWN_STYLE(显示"未知")
- 用 typeof === "string" 排除非字符串值(防御 TS 类型滥用)
*/
export function StatusBadge({
  status,
  lang = "cn",
  className,
}: {
  readonly status: TaskStatus | string | null | undefined;
  readonly lang?: "en" | "cn";
  readonly className?: string;
}) {
  // 1. undefined / null / "" → 加载中
  if (status === undefined || status === null || status === "") {
    return renderBadge(LOADING_STYLE, lang, className);
  }

  // 2. 已知 status → 走 STATUS_STYLES
  // 3. 未知 status(字符串但不在白名单) → 走 UNKNOWN_STYLE 并 warn
  const s =
    typeof status === "string" && status in STATUS_STYLES
      ? STATUS_STYLES[status as TaskStatus]
      : UNKNOWN_STYLE;

  if (s === UNKNOWN_STYLE) {
    // 上游数据漂移信号:warn 一次,方便定位后端协议与前端样式表的同步缺口
    console.warn(`[StatusBadge] 未识别的 status: ${String(status)}`);
  }
  return renderBadge(s, lang, className);
}

function renderBadge(
  s:
    | (typeof STATUS_STYLES)[TaskStatus]
    | typeof UNKNOWN_STYLE
    | typeof LOADING_STYLE,
  lang: "en" | "cn",
  className: string | undefined,
): React.ReactElement {
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
