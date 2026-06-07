import { DashboardHeader } from "@/components/dashboard/DashboardHeader";
import { StatsGrid } from "@/components/dashboard/StatsGrid";
import { RecentTasks } from "@/components/dashboard/RecentTasks";
import { AgentHealth } from "@/components/dashboard/AgentHealth";

/**
 * Dashboard 页面
 *
 * 布局:垂直堆叠 4 个区块,12px gap
 *  - Header(标题 + 时间筛选)
 *  - StatsGrid(5 张统计卡)
 *  - RecentTasks(最近任务表格)
 *  - AgentHealth(Agent 健康列表)
 *
 * 强制动态渲染:该页面依赖 zustand + TanStack Query 等客户端运行时,
 * 静态生成会导致 Functions cannot be passed 错误。
 */
export const dynamic = "force-dynamic";

export default function DashboardPage() {
  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-6 p-6">
      <DashboardHeader />
      <StatsGrid />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <RecentTasks />
        </div>
        <AgentHealth />
      </div>
    </div>
  );
}
