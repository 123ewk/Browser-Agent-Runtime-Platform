import { AgentWorkspace } from "@/components/agent";

/**
 * Agent Workspace 路由入口
 *
 * 三栏布局 + 底部 ChatInput 的"控制中心"。
 * 容器与 Sidebar 共享父布局,w-[260px] sidebar + 1fr main。
 */
export const dynamic = "force-dynamic";

export default function AgentPage() {
  return (
    <div className="h-screen w-full">
      <AgentWorkspace />
    </div>
  );
}
