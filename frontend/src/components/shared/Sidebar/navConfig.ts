/**
 * 图标名称 —— 用字符串标识,避免在 Server-Client 边界传递函数/组件
 * (Next.js App Router 不允许将 React 组件作为 prop 从 Server 传给 Client)
 */
export type IconName =
  | "LayoutDashboard"
  | "Workflow"
  | "ClipboardList"
  | "Settings"
  | "Activity";

/** 单个导航项的配置 —— Sidebar 用 */
export interface NavItem {
  readonly href: string;
  readonly label: string;
  readonly icon: IconName;
}

/** 主导航:4 个核心页面 —— Task Detail 不做导航项,从列表点击进入 */
export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: "LayoutDashboard" },
  { href: "/agent", label: "Workspace", icon: "Workflow" },
  { href: "/tasks", label: "Task Center", icon: "ClipboardList" },
  { href: "/settings", label: "Settings", icon: "Settings" },
];

/** 底部导航:Theme / Profile */
export const FOOTER_ITEMS: readonly NavItem[] = [
  { href: "/settings/theme", label: "Theme", icon: "Activity" },
  { href: "/settings/profile", label: "Profile", icon: "Activity" },
];
