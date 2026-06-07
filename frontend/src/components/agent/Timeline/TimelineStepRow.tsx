"use client";

import type { TimelineStep } from "@/types/timeline";
import { formatDuration } from "@/lib/format/duration";
import { stepKindMeta } from "./step-kind-meta";

interface TimelineStepRowProps {
  readonly step: TimelineStep;
}

export function TimelineStepRow({
  step,
}: TimelineStepRowProps): React.ReactElement {
  const { Icon, tone } = stepKindMeta[step.kind];
  return (
    <li className="flex gap-3">
      <div
        className={[
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
          tone,
        ].join(" ")}
      >
        <Icon size={14} />
      </div>
      <div className="flex-1 rounded-md border border-outline-variant bg-surface-container-lowest p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-on-surface">
            {step.title}
          </span>
          <span className="font-mono text-xs text-on-surface-variant">
            {formatDuration(step.durationMs)} · {step.tokens}t
          </span>
        </div>
        <p className="mt-1 text-sm text-on-surface-variant">{step.summary}</p>
      </div>
    </li>
  );
}
