/**
 * 指数退避调度器 —— 给 WS 重连用,封装 setTimeout 与重试计数
 * 上限 5 次后停止调度,避免静默无限循环
 */
export interface BackoffScheduler {
  schedule: (run: () => void) => void;
  cancel: () => void;
}

export function createBackoffScheduler(maxRetry = 5): BackoffScheduler {
  let retry = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  return {
    schedule(run) {
      if (retry >= maxRetry) return;
      const delay = Math.min(30_000, 1_000 * 2 ** retry);
      retry += 1;
      timer = setTimeout(run, delay);
    },
    cancel() {
      if (timer) clearTimeout(timer);
    },
  };
}
