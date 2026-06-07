"use client";

import {
  Activity,
  ClipboardList,
  LayoutDashboard,
  Settings,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import type { IconName, NavItem } from "./navConfig";

/** 图标名 → 组件映射 —— 在 Client Component 内解析,绕过 Server-Client 序列化限制 */
const ICON_MAP: Record<IconName, React.ComponentType<{ className?: string }>> = {
  LayoutDashboard,
  Workflow,
  ClipboardList,
  Settings,
  Activity,
};

/**
 * 导航项 —— active 态高亮
 *
 * active 判定:对 /tasks/[id] 用 startsWith 避免和 /tasks 冲突
 * (因为 /tasks/AF-0924 也以 /tasks 开头)。
 */
export function SidebarNavItem({ item }: { readonly item: NavItem }) {
  const pathname = usePathname();
  const isActive = item.href.startsWith("/tasks/")
    ? pathname.startsWith("/tasks/")
    : pathname === item.href || pathname.startsWith(`${item.href}/`);

  const Icon = ICON_MAP[item.icon];
  return (
    <Link
      href={item.href}
      className={cn(
        "flex items-center gap-3 rounded px-4 py-2 text-sm font-medium transition-colors",
        isActive
          ? "border-r-4 border-primary bg-surface-bright font-bold text-primary"
          : "text-on-surface-variant hover:bg-surface-container-low",
      )}
    >
      <Icon className="h-4 w-4" />
      <span>{item.label}</span>
    </Link>
  );
}
