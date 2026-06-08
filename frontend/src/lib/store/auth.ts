"use client";

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { AuthState, LoginPayload, RegisterPayload, UserOut } from "@/types/auth";
import { loginApi, logoutApi, registerApi } from "@/lib/api/auth";

/**
 * Auth 全局状态 —— 管理 token + user 持久化
 *
 * 设计要点:
 * - 使用 zustand/middleware 的 persist 把 token + user 存到 localStorage
 *   刷新页面后自动恢复登录态,避免每次进首页都跳登录
 * - logout 时只清前端态,后端的 Session 延迟双删交给 logoutApi
 * - 401 由 apiClient 响应拦截器统一处理 → 调 clearAuth()
 * - 当前后端没提供 GET /users/me,登录/注册后只拿到 token,
 *   user 信息用最小占位对象(username + id=pending),后续接 /me 再补全
 */
interface AuthStoreState {
  /** 当前 token —— 存在即视为已登录 */
  readonly token: string | null;
  /** 当前用户信息(从 username 推导 id=pending) */
  readonly user: UserOut | null;
  /** 是否处于登录/注册异步过程中(给 UI 禁用按钮用) */
  readonly isAuthenticating: boolean;

  /** 设置 token + user(登录/注册成功后调用) */
  setAuth: (auth: AuthState) => void;
  /** 清空登录态(注销 / 401 / 手动退出) */
  clearAuth: () => void;
  /** 登录:调后端 → 写 store */
  login: (payload: LoginPayload) => Promise<void>;
  /** 注册:调后端 → 写 store(注册即自动登录) */
  register: (payload: RegisterPayload) => Promise<void>;
  /** 注销:调后端 → 清 store */
  logout: () => Promise<void>;
}

/**
 * token → user 的最小推导 —— 后端没提供 /users/me,先用 username 占位
 *
 * 等后端实现 GET /users/me 后,这里改成调一次 /me 拿真实 id + created_at。
 */
function deriveUserFromToken(token: string, username: string): UserOut {
  return {
    id: "pending",
    username,
    created_at: new Date().toISOString(),
  };
}

export const useAuthStore = create<AuthStoreState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      isAuthenticating: false,

      setAuth: ({ token, user }) => set({ token, user }),

      clearAuth: () => set({ token: null, user: null }),

      login: async ({ username, password }) => {
        set({ isAuthenticating: true });
        try {
          const { access_token } = await loginApi({ username, password });
          set({
            token: access_token,
            user: deriveUserFromToken(access_token, username),
          });
        } finally {
          set({ isAuthenticating: false });
        }
      },

      register: async ({ username, password }) => {
        set({ isAuthenticating: true });
        try {
          const { access_token } = await registerApi({ username, password });
          set({
            token: access_token,
            user: deriveUserFromToken(access_token, username),
          });
        } finally {
          set({ isAuthenticating: false });
        }
      },

      logout: async () => {
        // 尽力而为:后端失败也清前端态
        try {
          await logoutApi();
        } catch (e) {
          // 后端注销失败不影响前端清态,但记录日志便于排查
          console.warn("[auth] 后端注销失败,仍清前端态:", e);
        }
        set({ token: null, user: null });
      },
    }),
    {
      name: "agenticflow-auth",
      storage: createJSONStorage(() => localStorage),
      // 只持久化 token + user,isAuthenticating 不持久化
      partialize: (state) => ({ token: state.token, user: state.user }),
    },
  ),
);

/**
 * 派生 hook —— 简化调用点
 *
 * 用法:
 *   const isAuthed = useIsAuthenticated();
 *   const user = useCurrentUser();
 *   const token = useAuthToken();
 */
export const useIsAuthenticated = () =>
  useAuthStore((s) => s.token !== null);

export const useCurrentUser = () => useAuthStore((s) => s.user);
export const useAuthToken = () => useAuthStore((s) => s.token);
