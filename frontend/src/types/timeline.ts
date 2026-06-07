/**
 * Timeline 步骤类型 —— Agent Workspace 中栏 + Task Detail 共用
 *
 * 步骤 kind 决定渲染样式(think / tool / observe / human / complete)
 */
export type TimelineStepKind =
  | "think"
  | "tool"
  | "observe"
  | "human"
  | "complete";

/**
 * 步骤渲染基类 —— UI 侧用 kind → 颜色/图标的映射表
 * 真实数据(LLM 思考全文、Tool 输出)从 task detail 拉取
 */
export interface TimelineStep {
  readonly id: string;
  readonly index: number;
  readonly kind: TimelineStepKind;
  readonly title: string;
  readonly summary: string;
  readonly startedAt: string;
  readonly durationMs: number;
  readonly tokens: number;
  /** tool / observe 类型时附带调用元数据 */
  readonly meta?: TimelineStepMeta;
}

export type TimelineStepMeta =
  | { readonly type: "tool"; readonly skillName: string }
  | { readonly type: "observe"; readonly pageUrl: string }
  | { readonly type: "human"; readonly question: string };
