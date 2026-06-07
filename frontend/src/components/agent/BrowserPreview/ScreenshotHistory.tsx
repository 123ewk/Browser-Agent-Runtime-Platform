import type { ScreenshotRef } from "@/types/task";

interface ScreenshotHistoryProps {
  readonly items: readonly ScreenshotRef[];
}

/**
 * 截图历史缩略图条
 *
 * 只取前 8 条,超过部分不在 UI 暴露,
 * 真实"翻历史"功能后续在 Task Detail 页面提供。
 */
export function ScreenshotHistory({
  items,
}: ScreenshotHistoryProps): React.ReactElement {
  const shown = items.slice(-8);
  return (
    <div className="border-t border-outline-variant bg-surface-container-low px-3 py-2">
      <div className="mb-1.5 text-xs font-medium text-on-surface-variant">
        预览历史
      </div>
      <div className="flex gap-2 overflow-x-auto">
        {shown.length === 0 ? (
          <span className="text-xs text-on-surface-variant">无历史截图</span>
        ) : (
          shown.map((s) => (
            <img
              key={s.id}
              src={s.url}
              alt={s.pageUrl}
              className="h-12 w-16 shrink-0 rounded-sm border border-outline-variant object-cover"
            />
          ))
        )}
      </div>
    </div>
  );
}
