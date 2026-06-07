import { Lock } from "lucide-react";

interface BrowserHeaderProps {
  readonly url: string;
}

/**
 * 浏览器窗口顶栏 —— macOS 红黄绿按钮 + URL
 *
 * 视觉只占"工具感"氛围,不做真实浏览器交互(前进/后退/刷新)
 * 因为操作目标在截图里,不是这个组件。
 */
export function BrowserHeader({
  url,
}: BrowserHeaderProps): React.ReactElement {
  return (
    <div className="flex items-center gap-2 border-b border-outline-variant bg-surface-container-low px-3 py-2">
      <div className="flex gap-1.5">
        <span className="h-3 w-3 rounded-full bg-error" />
        <span className="h-3 w-3 rounded-full bg-tertiary" />
        <span className="h-3 w-3 rounded-full bg-secondary" />
      </div>
      <div className="flex flex-1 items-center gap-1.5 rounded-md border border-outline-variant bg-surface-container-lowest px-2 py-1">
        <Lock size={12} className="text-on-surface-variant" />
        <span className="truncate font-mono text-xs text-on-surface-variant">
          {url}
        </span>
      </div>
    </div>
  );
}
