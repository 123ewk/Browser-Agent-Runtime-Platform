import type { ReactNode } from "react";
import { Sidebar } from "@/components/shared/Sidebar";
import { TopBar } from "@/components/shared/TopBar";
import { AuthGuard } from "@/components/auth/AuthGuard";
import { AuthModal } from "@/components/auth/AuthModal";

/**
 * 工作区布局 —— 共享 Sidebar + TopBar + AuthGuard
 *
 * 桌面端:固定 260px 侧边栏 + 流式主内容
 * 移动端:侧边栏折叠为抽屉(由 Sidebar 内部处理)
 *
 * AuthGuard 包裹主内容,未登录时盖半透明遮罩 + 居中"立即登录"提示
 * AuthModal 是全局唯一的登录/注册弹窗(任何地方触发都共用一个实例)
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
        <main className="flex-1 overflow-y-auto">
          <AuthGuard>{children}</AuthGuard>
        </main>
      </div>
      <AuthModal />
    </div>
  );
}
