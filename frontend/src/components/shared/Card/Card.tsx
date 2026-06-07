import { cn } from "@/lib/cn";

/** 通用 Card —— DESIGN.md 规定的白底 + 1px 边框 + 12px 圆角 */
export function Card({
  className,
  children,
}: {
  readonly className?: string;
  readonly children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-outline-variant bg-surface-container-lowest shadow-sm",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Card 头部 —— 标题区,可选 description / action 槽位 */
export function CardHeader({
  title,
  description,
  action,
  className,
}: {
  readonly title: string;
  readonly description?: string;
  readonly action?: React.ReactNode;
  readonly className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-start justify-between border-b border-outline-variant bg-surface-bright px-6 py-4",
        className,
      )}
    >
      <div>
        <h3 className="text-base font-semibold leading-tight text-on-surface">
          {title}
        </h3>
        {description ? (
          <p className="mt-1 text-sm text-on-surface-variant">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}
