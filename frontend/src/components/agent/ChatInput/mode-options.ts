import type { RunMode } from "@/types/chat";

/** 模式切换选项配置 —— UI 与数据分离,便于复用/单测 */
export interface ModeOption {
  readonly id: RunMode;
  readonly label: string;
  readonly hint: string;
}

export const RUN_MODE_OPTIONS: readonly ModeOption[] = [
  { id: "yolo", label: "YOLO", hint: "全自动" },
  { id: "semi", label: "Semi", hint: "半自动" },
];
