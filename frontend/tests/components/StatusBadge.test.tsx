import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "@/components/shared/StatusBadge";

describe("StatusBadge", () => {
  it("running 状态显示中文标签和 dot", () => {
    render(<StatusBadge status="running" />);
    expect(screen.getByText("运行中")).toBeInTheDocument();
  });

  it("success 状态显示中文标签", () => {
    render(<StatusBadge status="success" />);
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
});
