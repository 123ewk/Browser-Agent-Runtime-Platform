import { FOOTER_ITEMS, NAV_ITEMS } from "./navConfig";
import { SidebarNavItem } from "./SidebarNavItem";

/** 导航列表 —— 主导航 + 底部 Theme/Profile */
export function SidebarNav() {
  return (
    <nav className="flex flex-1 flex-col gap-1 overflow-y-auto px-4 pt-2">
      {NAV_ITEMS.map((item) => (
        <SidebarNavItem key={item.href} item={item} />
      ))}
      <div className="mt-auto border-t border-outline-variant pt-2">
        {FOOTER_ITEMS.map((item) => (
          <SidebarNavItem key={item.href} item={item} />
        ))}
      </div>
    </nav>
  );
}
