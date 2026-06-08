/**
 * 认证模块类型定义 —— 与后端 schema 严格对齐
 *
 * 字段约束来源:
 * - UserCreate: username 2-64, password 6-128
 * - UserLogin: 不校验长度,只验证凭据
 * - UserOut: id + username + created_at(不含 hashed_password)
 * - TokenResponse: access_token + token_type("bearer")
 */

/** 注册请求体 */
export interface RegisterPayload {
  readonly username: string;
  readonly password: string;
}

/** 登录请求体 */
export interface LoginPayload {
  readonly username: string;
  readonly password: string;
}

/** 后端返回的用户公开信息(已剥离 hashed_password) */
export interface UserOut {
  readonly id: string;
  readonly username: string;
  readonly created_at: string;
}

/** 后端返回的 token 响应 */
export interface TokenResponse {
  readonly access_token: string;
  readonly token_type: string;
}

/** 登录/注册成功后,前端持久化的认证态 */
export interface AuthState {
  readonly token: string;
  readonly user: UserOut;
}
