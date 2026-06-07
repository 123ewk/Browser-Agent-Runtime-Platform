import { Plus } from "lucide-react";

/**
 * New Workflow 按钮 —— Sidebar 顶部 CTA
 *
 * 暂不挂 onClick,后续接到"创建工作流"对话框时再补。
 * 当前直接显示 + 跳转 /agent 即可。
 */
export function NewWorkflowButton() {
  return (
    <div className="px-4 pb-4">
      <button
        type="button"
        className="flex w-full items-center justify-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-on-primary transition-colors hover:bg-primary-fixed-variant"
      >
        <Plus className="h-4 w-4" />
        New Workflow
      </button>
    </div>
  );
}
