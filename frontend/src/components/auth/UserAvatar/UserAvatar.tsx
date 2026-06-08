"use client";

import { useAuthModal } from "@/lib/store/auth-modal";
import { useIsAuthenticated, useCurrentUser, useAuthStore } from "@/lib/store/auth";

/**
 * 用户头像组件 —— 根据登录态切换显示
 *
 * 未登录:显示"登录"文字按钮(点击弹 AuthModal)
 * 已登录:显示用户名首字母圆形头像(点击后续可扩展下拉菜单)
 *
 * 设计:首字母一律大写;多字节字符(中文)取第一个字
 */
export function UserAvatar() {
  const isAuthed = useIsAuthenticated();
  const user = useCurrentUser();
  const logout = useAuthStore((s) => s.logout);
  const openLogin = useAuthModal((s) => s.openLogin);

  // 未登录态:渲染"登录"文字按钮
  if (!isAuthed) {
    return (
      <button
        type="button"
        onClick={openLogin}
        aria-label="登录"
        className="border-primary text-primary hover:bg-primary-container/10 h-8 rounded-full border px-3 text-xs font-medium transition-colors"
      >
        登录
      </button>
    );
  }

  // 已登录态:渲染首字母圆形头像
  const initial = (user?.username ?? "?").trim().charAt(0).toUpperCase();

  return (
    <div className="group relative">
      <button
        type="button"
        aria-label={`当前用户:${user?.username ?? ""}`}
        className="bg-primary text-on-primary flex h-8 w-8 items-center justify-center overflow-hidden rounded-full text-xs font-semibold shadow-sm transition-transform hover:scale-105"
        onClick={() => {
          // 简化交互:点击触发登出确认(后续可换自定义确认弹窗)
          if (window.confirm(`确定登出账号 "${user?.username}" 吗?`)) {
            void logout();
          }
        }}
      >
        {initial}
      </button>
    </div>
  );
}
