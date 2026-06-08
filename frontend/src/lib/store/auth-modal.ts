"use client";

import { create } from "zustand";

/**
 * AuthModal 开关状态机 —— 全局唯一开/关
 *
 * 用 zustand(而不是 Context)的原因:
 * - 任何组件(包括 TopBar、未登录遮罩内的"立即登录"按钮)都能直接 open()
 * - 不需要在 layout 层 Provider 包裹,避免新增耦合
 *
 * 用法:
 *   const { open, mode, openLogin, openRegister, close } = useAuthModal();
 *   <button onClick={openLogin}>登录</button>
 */
type AuthMode = "login" | "register";

interface AuthModalState {
  readonly open: boolean;
  readonly mode: AuthMode;
  openLogin: () => void;
  openRegister: () => void;
  /** 切换 Tab(login ↔ register),不影响 open 状态 */
  setMode: (mode: AuthMode) => void;
  close: () => void;
}

export const useAuthModal = create<AuthModalState>((set) => ({
  open: false,
  mode: "login",
  openLogin: () => set({ open: true, mode: "login" }),
  openRegister: () => set({ open: true, mode: "register" }),
  setMode: (mode) => set({ mode }),
  close: () => set({ open: false }),
}));
