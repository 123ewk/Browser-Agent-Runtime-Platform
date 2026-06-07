import { PlaceholderShell } from "@/components/shared";

export const dynamic = "force-dynamic";

export default function TaskDetailPage({
  params,
}: {
  readonly params: Promise<{ id: string }>;
}) {
  return (
    <PlaceholderShell
      title="Task Detail"
      description="任务详情:Overview / Timeline / Screenshots / Skill Trace / Cost Analytics —— 第四阶段实现"
    />
  );
}
