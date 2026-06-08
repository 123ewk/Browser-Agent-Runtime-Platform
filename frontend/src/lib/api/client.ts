import axios, { type AxiosError, type AxiosInstance } from "axios";
import { useAuthStore } from "@/lib/store/auth";

/**
 * 全局 axios 实例 —— 所有 lib/api/* 共享
 *
 * 拦截器职责:
 * - 请求拦截器:从 auth store 拿 token,自动注入 Authorization 头
 * - 响应拦截器:401 自动清登录态,业务层弹登录窗由调用方决定
 *
 * 注:不在拦截器里 import 任何 React / 弹窗组件,保持纯 IO 层。
 */

const baseURL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export const apiClient: AxiosInstance = axios.create({
  baseURL,
  timeout: 15_000,
  headers: { "Content-Type": "application/json" },
});

/** 请求拦截器 —— 自动注入 Bearer token */
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/** 响应拦截器 —— 401 时清登录态 */
apiClient.interceptors.response.use(
  (response) => response,
  (err: AxiosError) => {
    if (err.response?.status === 401) {
      // 静默清登录态;不重定向,让上层根据业务决定弹登录窗
      useAuthStore.getState().clearAuth();
    }
    return Promise.reject(err);
  },
);

/** 统一错误处理:把 axios 错误转成 ApiError */
export function toApiError(err: unknown): Error {
  if (axios.isAxiosError(err)) {
    const ax = err as AxiosError<{ message?: string }>;
    const message = ax.response?.data?.message ?? ax.message;
    return new Error(`[${ax.response?.status ?? "network"}] ${message}`);
  }
  return err instanceof Error ? err : new Error(String(err));
}
