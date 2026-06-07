import { NewWorkflowButton } from "./NewWorkflowButton";
import { SidebarBrand } from "./SidebarBrand";
import { SidebarNav } from "./SidebarNav";

/**
 * 侧边栏 —— 桌面端固定 260px,移动端抽屉(由父 layout 控)
 *
 * 不在这里管移动端开合,统一交给 Store;否则要拆 client/server 边界,
 * 增加复杂度。当前版本桌面端为主,移动端走 /agent 工作流。
 */
export function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 z-50 hidden h-full w-[260px] flex-col border-r border-outline-variant bg-surface-container-lowest py-6 md:flex">
      <SidebarBrand />
      <NewWorkflowButton />
      <SidebarNav />
    </aside>
  );
}
