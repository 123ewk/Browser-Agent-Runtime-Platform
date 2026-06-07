import { Bell, HelpCircle } from "lucide-react";

/** 通知 + 帮助按钮组 —— TopBar 右上 */
export function TopBarActions() {
  return (
    <div className="flex items-center gap-4">
      <button
        type="button"
        aria-label="通知"
        className="text-on-surface-variant transition-colors hover:text-primary"
      >
        <Bell className="h-5 w-5" />
      </button>
      <button
        type="button"
        aria-label="帮助"
        className="text-on-surface-variant transition-colors hover:text-primary"
      >
        <HelpCircle className="h-5 w-5" />
      </button>
    </div>
  );
}
