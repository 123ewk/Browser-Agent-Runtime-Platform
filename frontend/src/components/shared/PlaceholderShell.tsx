import { Construction } from "lucide-react";

/** 通用占位页 —— 第二/三阶段页面未实现时统一展示 */
export function PlaceholderShell({
  title,
  description,
}: {
  readonly title: string;
  readonly description: string;
}) {
  return (
    <div className="mx-auto flex max-w-[1400px] flex-col items-center justify-center gap-4 p-12 text-center">
      <Construction className="h-10 w-10 text-on-surface-variant" />
      <h1 className="text-2xl font-semibold text-on-background">{title}</h1>
      <p className="max-w-md text-sm text-on-surface-variant">{description}</p>
    </div>
  );
}
