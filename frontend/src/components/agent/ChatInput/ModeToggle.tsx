"use client";

import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";
import { RUN_MODE_OPTIONS } from "./mode-options";

/**
 * YOLO / Semi 模式切换 —— radio group 风格
 * 用 button + aria-checked 而非 <input type="radio">,
 * 视觉更贴近"开关",且无 form 库依赖
 */
export function ModeToggle(): React.ReactElement {
  const runMode = useAgentWorkspaceStore((s) => s.runMode);
  const setRunMode = useAgentWorkspaceStore((s) => s.setRunMode);

  return (
    <div
      className="flex items-center rounded-md border border-outline-variant bg-surface-container-low p-0.5"
      role="radiogroup"
      aria-label="运行模式"
    >
      {RUN_MODE_OPTIONS.map((o) => {
        const active = o.id === runMode;
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => setRunMode(o.id)}
            title={o.hint}
            className={[
              "rounded px-2.5 py-1 text-xs font-medium transition-colors",
              active
                ? "bg-primary text-on-primary"
                : "text-on-surface-variant hover:bg-surface-container",
            ].join(" ")}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
