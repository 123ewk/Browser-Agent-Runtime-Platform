"use client";

import {
  Brain,
  Cog,
  Eye,
  Hand,
  CheckCircle2,
  Camera,
  AlertTriangle,
  Activity,
  Play,
} from "lucide-react";
import type { EventType } from "@/types/chat";

/**
 * EventType → 视觉映射 —— 集中放这里,新增事件类型只动这张表
 */
type StepMeta = { Icon: typeof Brain; tone: string; label: string };

export const stepKindMeta: Record<EventType, StepMeta> = {
  WORKER_READY: {
    Icon: Play,
    tone: "text-green-600 bg-green-100",
    label: "Worker 就绪",
  },
  WORKER_HEARTBEAT: {
    Icon: Activity,
    tone: "text-on-surface-variant bg-surface-container",
    label: "心跳",
  },
  STEP_START: {
    Icon: Play,
    tone: "text-primary bg-primary-container/20",
    label: "步骤开始",
  },
  STEP_COMPLETE: {
    Icon: CheckCircle2,
    tone: "text-secondary bg-secondary-container/20",
    label: "步骤完成",
  },
  SCREENSHOT: {
    Icon: Camera,
    tone: "text-tertiary bg-tertiary-container/20",
    label: "截图",
  },
  PROGRESS: {
    Icon: Activity,
    tone: "text-primary bg-primary-container/20",
    label: "进度",
  },
  NEED_CONFIRM: {
    Icon: Hand,
    tone: "text-primary bg-primary-container/30 ring-1 ring-primary",
    label: "等待确认",
  },
  ERROR: {
    Icon: AlertTriangle,
    tone: "text-error bg-error-container/20",
    label: "错误",
  },
  TASK_FINISHED: {
    Icon: CheckCircle2,
    tone: "text-secondary bg-secondary-container/30",
    label: "任务完成",
  },
  TASK_STATE_CHANGED: {
    Icon: Activity,
    tone: "text-on-surface-variant bg-surface-container",
    label: "状态变更",
  },
  COMMAND_ACK: {
    Icon: Cog,
    tone: "text-on-surface-variant bg-surface-container",
    label: "命令确认",
  },
  WATCHDOG_TIMEOUT: {
    Icon: AlertTriangle,
    tone: "text-error bg-error-container/20",
    label: "心跳超时",
  },
};
