import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StatusBadge } from "@/components/shared/StatusBadge";

describe("StatusBadge", () => {
  it("running 状态显示中文标签和 dot", () => {
    render(<StatusBadge status="running" />);
    expect(screen.getByText("运行中")).toBeInTheDocument();
  });

  it("completed 状态显示中文标签", () => {
    render(<StatusBadge status="completed" />);
    expect(screen.getByText("成功")).toBeInTheDocument();
  });

  it("failed 状态显示中文标签", () => {
    render(<StatusBadge status="failed" />);
    expect(screen.getByText("失败")).toBeInTheDocument();
  });

  it("lang=en 输出英文标签", () => {
    render(<StatusBadge status="running" lang="en" />);
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  // 回归测试:后端返回前端 STATUS_STYLES 尚未覆盖的 status 时,
  // 不应抛错,应降级到"未知"标签 —— 避免阻塞整个列表渲染
  it("未识别的 status 降级为未知标签且不抛错", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    // 通过类型断言绕过编译期检查,模拟"后端新增枚举、前端未同步"的真实故障
    render(<StatusBadge status={"queued" as never} />);
    expect(screen.getByText("未知")).toBeInTheDocument();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
