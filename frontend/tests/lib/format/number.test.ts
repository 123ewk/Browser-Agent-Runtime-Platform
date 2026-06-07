import { describe, expect, it } from "vitest";
import { formatCompactNumber } from "@/lib/format/number";

describe("formatCompactNumber", () => {
  it("< 1000 原样输出", () => {
    expect(formatCompactNumber(0)).toBe("0");
    expect(formatCompactNumber(999)).toBe("999");
  });

  it("千级显示 1.2K", () => {
    expect(formatCompactNumber(1234)).toBe("1.2K");
  });

  it("百万级显示 1.2M", () => {
    expect(formatCompactNumber(1_200_000)).toBe("1.2M");
  });
});
