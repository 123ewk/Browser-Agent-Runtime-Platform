"use client";

import { Brain, Cog, Eye, Hand, CheckCircle2 } from "lucide-react";
import type { TimelineStepKind } from "@/types/timeline";

/**
 * kind → 视觉映射 —— 集中放这里,新增类型只动这张表
 * 颜色用 Tailwind class 字符串(lucide 用 currentColor,需要稳定 class)
 */
export const stepKindMeta: Readonly<
  Record<TimelineStepKind, { Icon: typeof Brain; tone: string }>
> = {
  think: { Icon: Brain, tone: "text-tertiary bg-tertiary-container/20" },
  tool: { Icon: Cog, tone: "text-primary bg-primary-container/20" },
  observe: { Icon: Eye, tone: "text-secondary bg-secondary-container/20" },
  human: {
    Icon: Hand,
    tone: "text-primary bg-primary-container/30 ring-1 ring-primary",
  },
  complete: {
    Icon: CheckCircle2,
    tone: "text-secondary bg-secondary-container/30",
  },
};
