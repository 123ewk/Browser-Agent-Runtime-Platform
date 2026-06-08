"use client";

import { type CSSProperties } from "react";

/**
 * Material Symbols 图标组件 —— 封装 Google Material Symbols Outlined
 *
 * 与 lucide-react 并存:Material Symbols 用于"品牌/平台类"图标(hub/cloud/fingerprint)
 * lucide-react 用于"UI 操作类"图标(Bell/HelpCircle/X 等)
 *
 * 用法:
 *   <MaterialSymbol name="hub" size={28} fill />
 *   <MaterialSymbol name="close" size={20} />
 */
export interface MaterialSymbolProps {
  /** 图标名(对应 Material Symbols 字体中的 ligature 名) */
  readonly name: string;
  /** 像素尺寸(同时控制 width/height/fontSize) */
  readonly size?: number;
  /** 颜色 —— 默认 currentColor(继承父级 text-* 类) */
  readonly color?: string;
  /** 填充模式 —— 开启后图标变为实心 */
  readonly fill?: boolean;
  /** 字重 100-700 —— 默认 400(常规) */
  readonly weight?: 100 | 200 | 300 | 400 | 500 | 600 | 700;
  /** 自定义类名 */
  readonly className?: string;
}

export function MaterialSymbol({
  name,
  size = 24,
  color,
  fill = false,
  weight = 400,
  className,
}: MaterialSymbolProps) {
  // font-variation-settings 控制 FILL/wght/GRAD/opsz 四个轴
  const style: CSSProperties = {
    fontSize: size,
    lineHeight: 1,
    width: size,
    height: size,
    color,
    fontVariationSettings: `'FILL' ${fill ? 1 : 0}, 'wght' ${weight}, 'GRAD' 0, 'opsz' ${size}`,
  };

  return (
    <span
      className={`material-symbols-outlined leading-none ${className ?? ""}`}
      style={style}
      data-icon={name}
      aria-hidden="true"
    >
      {name}
    </span>
  );
}
