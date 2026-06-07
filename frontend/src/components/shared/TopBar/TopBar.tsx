import { HealthIndicator } from "./HealthIndicator";
import { TopBarActions } from "./TopBarActions";

/**
 * 顶部导航条 —— 高度 64px,sticky 在主内容上沿
 *
 * 左侧:健康状态(后续也可放面包屑)
 * 右侧:通知 / 帮助 / 头像
 * 搜索框不放这里 —— Task Center 那种带搜索的页面在页面内做
 */
export function TopBar() {
  return (
    <header className="sticky top-0 z-40 flex h-16 items-center justify-between border-b border-outline-variant bg-surface px-6">
      <HealthIndicator status="healthy" />
      <div className="flex items-center gap-4">
        <TopBarActions />
        <div
          aria-label="用户头像"
          className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full border border-outline-variant bg-surface-container-highest"
        >
          <span className="text-xs text-on-surface-variant">U</span>
        </div>
      </div>
    </header>
  );
}
