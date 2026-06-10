"use client";

import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";

/**
 * New Workflow 按钮 —— Sidebar 顶部 CTA
 *
 * 行为: 跳转 /agent 工作区, 由底部 ChatInput 收 goal 提交。
 * 用 onClick + useRouter 而非 <Link>: 保留原实心按钮视觉,避免样式 override。
 */
export function NewWorkflowButton() {
  const router = useRouter();

  return (
    <div className="px-4 pb-4">
      <button
        type="button"
        onClick={() => router.push("/agent")}
        className="flex w-full items-center justify-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-on-primary transition-colors hover:bg-primary-fixed-variant"
      >
        <Plus className="h-4 w-4" />
        New Workflow
      </button>
    </div>
  );
}
