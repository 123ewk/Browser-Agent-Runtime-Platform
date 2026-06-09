import { apiClient } from "./client";
import type { LoginPayload, RegisterPayload, TokenResponse, UserOut } from "@/types/auth";

/**
 * 认证 API 调用层 —— 与后端 /auth/* 端点对应
 *
 * 后端实现:
 * - POST /auth/register: 201 + JWT,409 表示用户名冲突
 * - POST /auth/login: 200 + JWT,401 表示凭据错误
 * - POST /auth/logout: 204,需要 Bearer token
 * - GET  /auth/me: 200 + UserOut,需要 Bearer token
 *
 * 返回原始 TokenResponse,业务层(store)负责把它和 user 信息组装成 AuthState。
 */

/** 注册 —— 返回 JWT,业务层需要再 GET /users/me 拿用户信息 */
export async function registerApi(payload: RegisterPayload): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/register", payload);
  return data;
}

/** 登录 —— 返回 JWT,业务层需要再 GET /users/me 拿用户信息 */
export async function loginApi(payload: LoginPayload): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/login", payload);
  return data;
}

/** 注销 —— 后端做 Session 延迟双删 */
export async function logoutApi(): Promise<void> {
  await apiClient.post("/auth/logout");
}

/** GET /auth/me —— 获取当前登录用户信息(补全 id + created_at) */
export async function getCurrentUser(): Promise<UserOut> {
  const { data } = await apiClient.get<UserOut>("/auth/me");
  return data;
}
