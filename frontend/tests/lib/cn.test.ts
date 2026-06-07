import { describe, expect, it } from "vitest";
import { cn } from "@/lib/cn";

describe("cn", () => {
  it("合并多个 className", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("过滤 falsy 值", () => {
    expect(cn("a", false, null, undefined, "b")).toBe("a b");
  });

  it("twMerge 解决冲突:后者覆盖前者", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
  });

  it("支持条件 className(对象形式)", () => {
    expect(cn("base", { active: true, disabled: false })).toBe("base active");
  });
});
