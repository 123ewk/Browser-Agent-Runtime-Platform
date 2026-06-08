import { z } from "zod";

/**
 * 登录表单校验 —— 与后端 UserLogin 对齐
 *
 * 后端只校验凭据是否匹配,不做长度检查,但前端仍要求非空,
 * 避免把明显无意义的请求送到后端。
 */
export const loginSchema = z.object({
  username: z
    .string()
    .min(1, "请输入用户名")
    .max(64, "用户名最多 64 个字符"),
  password: z
    .string()
    .min(1, "请输入密码")
    .max(128, "密码最多 128 个字符"),
});

export type LoginFormValues = z.infer<typeof loginSchema>;

/**
 * 注册表单校验 —— 与后端 UserCreate 严格对齐
 *
 * 后端约束:
 * - username: 2-64 字符
 * - password: 6-128 字符
 *
 * 前端在 zod 阶段就拦截,避免无效请求打到后端。
 */
export const registerSchema = z.object({
  username: z
    .string()
    .min(2, "用户名至少 2 个字符")
    .max(64, "用户名最多 64 个字符")
    .regex(/^[a-zA-Z0-9_-]+$/, "只能包含字母、数字、下划线和短横线"),
  password: z
    .string()
    .min(6, "密码至少 6 个字符")
    .max(128, "密码最多 128 个字符"),
});

export type RegisterFormValues = z.infer<typeof registerSchema>;
