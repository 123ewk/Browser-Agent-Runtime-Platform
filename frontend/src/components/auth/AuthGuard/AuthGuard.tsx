"use client";

import { type ReactNode } from "react";
import { motion } from "framer-motion";
import { useIsAuthenticated } from "@/lib/store/auth";
import { useAuthModal } from "@/lib/store/auth-modal";
import { MaterialSymbol } from "@/components/ui/MaterialSymbol";

/**
 * 未登录遮罩组件 —— 盖在工作区主内容上,引导用户登录
 *
 * 设计要点(对照需求:用户没有登录时就不可以使用功能):
 * - 不跳转页面(用户能看到后台全貌,产生使用动机)
 * - 半透明遮罩 + 模糊,底层内容可见但不可操作
 * - 居中提示卡片:文案 + "立即登录"按钮
 * - 已登录态:完全不渲染,不影响性能
 */
export function AuthGuard({ children }: { readonly children: ReactNode }) {
  const isAuthed = useIsAuthenticated();
  const openLogin = useAuthModal((s) => s.openLogin);

  if (isAuthed) return <>{children}</>;

  return (
    <div className="relative">
      {/* 底层内容(可看到但不可交互) */}
      <div className="pointer-events-none select-none opacity-50 blur-[1px]">
        {children}
      </div>

      {/* 遮罩 + 居中提示 */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className="absolute inset-0 z-30 flex items-center justify-center bg-black/30 backdrop-blur-[2px]"
        role="dialog"
        aria-label="需要登录"
      >
        <motion.div
          initial={{ scale: 0.9, opacity: 0, y: 20 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          transition={{
            type: "spring",
            stiffness: 260,
            damping: 22,
            delay: 0.1,
          }}
          className="bg-surface-container-lowest border-outline-variant mx-4 max-w-md rounded-2xl border p-8 text-center shadow-2xl"
        >
          <div className="bg-primary shadow-primary/20 mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl shadow-lg">
            <MaterialSymbol
              name="lock"
              size={28}
              color="#ffffff"
              weight={500}
            />
          </div>
          <h2 className="font-headline-sm text-on-surface mb-2 text-headline-sm">
            请先登录
          </h2>
          <p className="text-on-surface-variant font-body-sm text-body-sm mb-6">
            登录后即可使用 AgenticFlow 的全部功能
          </p>
          <button
            type="button"
            onClick={openLogin}
            className="bg-primary text-on-primary shadow-primary/20 h-11 w-full rounded-lg font-semibold shadow-md transition-all hover:bg-primary-container active:scale-[0.98]"
          >
            立即登录
          </button>
        </motion.div>
      </motion.div>
    </div>
  );
}
