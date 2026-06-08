/**
 * 相对时间格式化 —— "2 分钟前"、"3 小时前"
 *
 * 不引 dayjs/date-fns(零依赖):用 Intl.RelativeTimeFormat 即可覆盖
 * 80% 场景,API 表格里"更新时间"列就是这种格式。
 */

/** 时间差粒度阈值(秒) */
const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

export function formatRelativeTime(input: Date | string | number): string {
  const target = input instanceof Date ? input : new Date(input);
  const diffSec = Math.round((target.getTime() - Date.now()) / 1000);
  const absSec = Math.abs(diffSec);

  // 用 Intl 输出中文 locale
  const rtf = new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" });

  if (absSec < MINUTE) return rtf.format(diffSec, "second");
  if (absSec < HOUR) return rtf.format(Math.round(diffSec / MINUTE), "minute");
  if (absSec < DAY) return rtf.format(Math.round(diffSec / HOUR), "hour");
  if (absSec < MONTH) return rtf.format(Math.round(diffSec / DAY), "day");
  if (absSec < YEAR) return rtf.format(Math.round(diffSec / MONTH), "month");
  return rtf.format(Math.round(diffSec / YEAR), "year");
}
