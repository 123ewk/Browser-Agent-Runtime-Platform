import axios, { type AxiosError, type AxiosInstance } from "axios";

/**
 * 全局 axios 实例 —— 所有 lib/api/* 共享
 *
 * - 走 `NEXT_PUBLIC_API_BASE_URL` 环境变量,避免硬编码
 * - 超时 15s(浏览器操作任务响应可能慢,但不至于 1min)
 * - 401 自动清登录态(后续接 NextAuth 时再实现)
 */
const baseURL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export const apiClient: AxiosInstance = axios.create({
  baseURL,
  timeout: 15_000,
  headers: { "Content-Type": "application/json" },
});

/** 统一错误处理:把 axios 错误转成 ApiError */
export function toApiError(err: unknown): Error {
  if (axios.isAxiosError(err)) {
    const ax = err as AxiosError<{ message?: string }>;
    const message = ax.response?.data?.message ?? ax.message;
    return new Error(`[${ax.response?.status ?? "network"}] ${message}`);
  }
  return err instanceof Error ? err : new Error(String(err));
}
