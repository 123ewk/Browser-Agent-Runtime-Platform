/**
 * 时间格式工具 —— ms → "1.2s" / "850ms"
 * 与 lib/format/time.ts(相对时间)区分,这是绝对耗时
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
