"use client";

import { type ReactNode, useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/cn";

/**
 * 通用 Dialog 组件 —— 基于设计稿的遮罩 + 弹窗卡片
 *
 * 设计要点:
 * - 遮罩层:fixed 全屏 + bg-black/60 + backdrop-blur-sm
 * - 卡片:max-w-[400px] + 居中 + 阴影 + 圆角
 * - 动画:遮罩淡入 + 卡片 spring 弹入,关闭时反向
 * - 焦点:打开时锁定 body 滚动,按 Esc 关闭
 */
export interface DialogProps {
  /** 是否打开 */
  readonly open: boolean;
  /** 关闭回调(点击遮罩 / Esc 都会触发) */
  readonly onClose: () => void;
  /** 弹窗卡片内部内容 */
  readonly children: ReactNode;
  /** 自定义弹窗卡片类名(覆盖 max-w / 宽度等) */
  readonly className?: string;
  /** 是否点击遮罩关闭 —— 默认 true */
  readonly closeOnOverlay?: boolean;
}

export function Dialog({
  open,
  onClose,
  children,
  className,
  closeOnOverlay = true,
}: DialogProps) {
  // 打开时锁滚动 + Esc 关闭
  useEffect(() => {
    if (!open) return;

    // 锁 body 滚动,避免遮罩后面的页面跟着滚
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);

    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", handleKey);
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
          onClick={closeOnOverlay ? onClose : undefined}
          aria-modal="true"
          role="dialog"
        >
          {/* 弹窗卡片 —— onClick 阻止冒泡,避免点击卡片内空白触发关闭 */}
          <motion.div
            className={cn(
              "relative w-full max-w-[400px] overflow-hidden rounded-[1.5rem] border border-outline-variant bg-surface-container-lowest p-8 shadow-2xl",
              className,
            )}
            initial={{ scale: 0.9, opacity: 0, y: 20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.95, opacity: 0 }}
            transition={{
              type: "spring",
              stiffness: 300,
              damping: 25,
              mass: 0.8,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
