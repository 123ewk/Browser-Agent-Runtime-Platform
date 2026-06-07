import { describe, expect, it } from "vitest";
import { formatUsd } from "@/lib/format/currency";

describe("formatUsd", () => {
  it("< 0.01 显示占位符", () => {
    expect(formatUsd(0)).toBe("<$0.01");
    expect(formatUsd(0.005)).toBe("<$0.01");
  });

  it("正常金额显示 2 位小数", () => {
    expect(formatUsd(0.45)).toBe("$0.45");
    expect(formatUsd(1.2)).toBe("$1.20");
  });

  it("大金额带千分位", () => {
    expect(formatUsd(1234.5)).toBe("$1,234.50");
  });
});
