import type { ReactNode } from "react";
import { Sidebar } from "@/components/shared/Sidebar";
import { TopBar } from "@/components/shared/TopBar";

/**
 * 工作区布局 —— 共享 Sidebar + TopBar
 *
 * 桌面端:固定 260px 侧边栏 + 流式主内容
 * 移动端:侧边栏折叠为抽屉(由 Sidebar 内部处理)
 */
export default function WorkspaceLayout({
  children,
}: {
  readonly children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-background text-on-background">
      <Sidebar />
      <div className="flex flex-1 flex-col md:ml-[260px]">
        <TopBar />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
