/**
 * 货币格式化 —— 用于 Task Center / Dashboard 的 Cost 列
 *
 * 固定 USD 符号前缀(项目当前只对接 USD 计费);
 * 金额 < 0.01 显示 "<$0.01",否则走 Intl 保留 2 位小数。
 */
export function formatUsd(amount: number): string {
  if (amount < 0.01) return "<$0.01";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}
