import { describe, expect, it } from "vitest";
import { formatRelativeTime } from "@/lib/format/time";

describe("formatRelativeTime", () => {
  it("过去 1 分钟以内显示 N 秒前", () => {
    const past = new Date(Date.now() - 30_000);
    expect(formatRelativeTime(past)).toMatch(/秒/);
  });

  it("过去 1 小时显示 N 分钟前", () => {
    const past = new Date(Date.now() - 5 * 60_000);
    expect(formatRelativeTime(past)).toMatch(/分钟/);
  });

  it("接受 ISO 字符串", () => {
    const past = new Date(Date.now() - 60_000).toISOString();
    expect(formatRelativeTime(past)).toMatch(/分钟/);
  });

  it("未来时间也能正常格式化(负数差)", () => {
    const future = new Date(Date.now() + 60_000);
    expect(formatRelativeTime(future)).toMatch(/分钟/);
  });
});
