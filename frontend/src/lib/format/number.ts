/**
 * 大数字缩写 —— 1.2K / 1.2M / 3.4B
 *
 * 用于 Dashboard 的"今日 Tokens 1.2M"等场景。
 * 数字 < 1000 时原样输出(避免 999 显示为 999)。
 */
export function formatCompactNumber(value: number): string {
  if (value < 1000) return String(value);
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}
