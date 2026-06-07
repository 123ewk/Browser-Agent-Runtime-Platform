import { ImageOff } from "lucide-react";
import type { ScreenshotRef } from "@/types/task";

interface BrowserScreenshotProps {
  readonly screenshot: ScreenshotRef | null;
}

/**
 * 当前截图展示区
 *
 * 真实截图走 S3 预签名 URL;在没有数据时显示空态,
 * 而不是空白,避免 Agent 运行前给用户"页面错误"的错觉。
 */
export function BrowserScreenshot({
  screenshot,
}: BrowserScreenshotProps): React.ReactElement {
  return (
    <div className="relative flex-1 overflow-hidden bg-surface-container">
      {screenshot ? (
        <img
          src={screenshot.url}
          alt={`browser preview ${screenshot.pageUrl}`}
          className="h-full w-full object-contain"
        />
      ) : (
        <div className="flex h-full flex-col items-center justify-center gap-2 text-on-surface-variant">
          <ImageOff size={28} />
          <span className="text-sm">Agent 暂未产生截图</span>
        </div>
      )}
    </div>
  );
}
