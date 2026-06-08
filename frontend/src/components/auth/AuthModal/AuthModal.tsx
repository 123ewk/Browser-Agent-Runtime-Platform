"use client";

import { type FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { AxiosError } from "axios";
import { motion, AnimatePresence } from "framer-motion";
import { Dialog } from "@/components/ui/Dialog";
import { MaterialSymbol } from "@/components/ui/MaterialSymbol";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/lib/store/auth";
import { useAuthModal } from "@/lib/store/auth-modal";
import {
  loginSchema,
  registerSchema,
  type LoginFormValues,
  type RegisterFormValues,
} from "@/lib/validations/auth";
import { toApiError } from "@/lib/api/client";

/**
 * 登录/注册弹窗 —— 设计稿还原
 *
 * 交互细节(对照 code (6).html):
 * - 品牌区:紫色 hub 图标 + AgenticFlow 标题 + 副标题
 * - Tab 切换:登录/注册,带下划线指示器
 * - 登录表单:邮箱 + 密码 + 保持登录状态 + 忘记密码
 * - 注册表单:用户名 + 邮箱 + 密码 + 服务条款
 * - 底部:第三方登录(GitHub + SSO)+ 切换链接
 * - 服务端错误:顶部 alert 横条(error-container 色)
 * - 动画:卡片 spring 弹入 + Tab 表单横向滑动
 *
 * 表单方案:受控 input + zod safeParse 校验。
 * 不引 react-hook-form —— 弹窗只有 2 个字段,zod 手校验代码量更少。
 */
export function AuthModal() {
  const { open, mode, setMode, close } = useAuthModal();
  const router = useRouter();
  const isAuthenticating = useAuthStore((s) => s.isAuthenticating);

  return (
    <Dialog open={open} onClose={close}>
      {/* 关闭按钮 */}
      <button
        type="button"
        onClick={close}
        aria-label="关闭"
        className="absolute top-6 right-6 rounded-full p-1 text-on-surface-variant transition-colors hover:bg-surface-variant/20"
      >
        <MaterialSymbol name="close" size={20} />
      </button>

      {/* 品牌区 */}
      <div className="mb-8 flex flex-col items-center text-center">
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-primary shadow-lg shadow-primary/20">
          <MaterialSymbol name="hub" size={28} color="#ffffff" fill weight={500} />
        </div>
        <h1 className="font-headline-md text-headline-md text-on-surface mb-1">
          AgenticFlow
        </h1>
        <p className="text-on-surface-variant font-body-sm opacity-80">
          AI 编排控制台
        </p>
      </div>

      {/* Tab 切换 */}
      <AuthTabs mode={mode} onChange={setMode} />

      {/* 表单区 —— mode 切换时用 motion 控制横向滑动 */}
      <div className="relative min-h-[300px]">
        <AnimatePresence mode="wait" initial={false}>
          {mode === "login" ? (
            <motion.div
              key="login"
              initial={{ opacity: 0, x: -16 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 16 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
            >
              <LoginForm
                isSubmitting={isAuthenticating}
                onSuccess={() => {
                  close();
                  router.refresh();
                }}
              />
            </motion.div>
          ) : (
            <motion.div
              key="register"
              initial={{ opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -16 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
            >
              <RegisterForm
                isSubmitting={isAuthenticating}
                onSuccess={() => {
                  close();
                  router.refresh();
                }}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* 第三方登录 + 切换链接 */}
      <SocialAuthSection mode={mode} onSwitchMode={setMode} />
    </Dialog>
  );
}

/* ====================== 子组件 ====================== */

/** Tab 切换栏(下划线指示器) */
function AuthTabs({
  mode,
  onChange,
}: {
  readonly mode: "login" | "register";
  readonly onChange: (m: "login" | "register") => void;
}) {
  return (
    <div className="mb-6 flex border-b border-outline-variant">
      {(["login", "register"] as const).map((m) => {
        const isActive = m === mode;
        return (
          <button
            key={m}
            type="button"
            onClick={() => onChange(m)}
            className={cn(
              "relative flex-1 py-3 font-medium transition-colors duration-300",
              isActive
                ? "text-primary"
                : "text-on-surface-variant hover:text-on-surface",
            )}
          >
            {m === "login" ? "登录" : "注册"}
            {isActive && (
              <motion.div
                layoutId="auth-tab-indicator"
                className="absolute right-0 bottom-0 left-0 h-0.5 bg-primary"
                transition={{ type: "spring", stiffness: 380, damping: 30 }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}

/** 通用输入框 —— 统一 label + input + 错误样式 */
function FormField({
  label,
  error,
  children,
  rightSlot,
}: {
  readonly label: string;
  readonly error?: string;
  readonly children: React.ReactNode;
  readonly rightSlot?: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="block text-sm font-medium text-on-surface-variant">
          {label}
        </label>
        {rightSlot}
      </div>
      {children}
      {error && <p className="text-xs text-error">{error}</p>}
    </div>
  );
}

const inputClass =
  "w-full h-10 px-3 bg-surface-container-lowest border rounded-lg focus:ring-2 outline-none transition-all placeholder:text-outline text-sm text-on-surface";

/** 登录表单 */
function LoginForm({
  isSubmitting,
  onSuccess,
}: {
  readonly isSubmitting: boolean;
  readonly onSuccess: () => void;
}) {
  const [serverError, setServerError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<
    Partial<Record<keyof LoginFormValues, string>>
  >({});
  const [values, setValues] = useState<LoginFormValues>({
    username: "",
    password: "",
  });
  const login = useAuthStore((s) => s.login);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setServerError(null);
    setFieldErrors({});

    const parsed = loginSchema.safeParse(values);
    if (!parsed.success) {
      const errs: Partial<Record<keyof LoginFormValues, string>> = {};
      for (const issue of parsed.error.issues) {
        const k = issue.path[0] as keyof LoginFormValues;
        errs[k] = issue.message;
      }
      setFieldErrors(errs);
      return;
    }

    try {
      await login(parsed.data);
      onSuccess();
    } catch (err) {
      setServerError(parseServerError(err));
    }
  };

  return (
    <form className="space-y-5" onSubmit={onSubmit} noValidate>
      <ServerErrorBanner message={serverError} />

      <FormField label="用户名" error={fieldErrors.username}>
        <input
          type="text"
          placeholder="请输入用户名"
          autoComplete="username"
          value={values.username}
          onChange={(e) =>
            setValues((v) => ({ ...v, username: e.target.value }))
          }
          className={cn(
            inputClass,
            fieldErrors.username
              ? "border-error focus:border-error focus:ring-error/20"
              : "border-outline-variant focus:border-primary focus:ring-primary/20",
          )}
        />
      </FormField>

      <FormField
        label="密码"
        error={fieldErrors.password}
        rightSlot={
          <a className="text-xs text-primary hover:underline" href="#">
            忘记密码？
          </a>
        }
      >
        <input
          type="password"
          placeholder="••••••••"
          autoComplete="current-password"
          value={values.password}
          onChange={(e) =>
            setValues((v) => ({ ...v, password: e.target.value }))
          }
          className={cn(
            inputClass,
            fieldErrors.password
              ? "border-error focus:border-error focus:ring-error/20"
              : "border-outline-variant focus:border-primary focus:ring-primary/20",
          )}
        />
      </FormField>

      <div className="flex items-center gap-2 pt-2">
        <input
          id="remember"
          type="checkbox"
          className="text-primary focus:ring-primary h-4 w-4 rounded border-outline-variant"
        />
        <label htmlFor="remember" className="text-on-surface-variant text-sm">
          保持登录状态
        </label>
      </div>

      <button
        type="submit"
        disabled={isSubmitting}
        className="bg-primary text-on-primary shadow-primary/10 mt-2 h-11 w-full rounded-lg font-semibold shadow-md transition-all hover:bg-primary-container active:scale-[0.98] disabled:opacity-60"
      >
        {isSubmitting ? "登录中..." : "立即登录"}
      </button>
    </form>
  );
}

/** 注册表单 */
function RegisterForm({
  isSubmitting,
  onSuccess,
}: {
  readonly isSubmitting: boolean;
  readonly onSuccess: () => void;
}) {
  const [serverError, setServerError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<
    Partial<Record<keyof RegisterFormValues, string>>
  >({});
  const [values, setValues] = useState<RegisterFormValues>({
    username: "",
    password: "",
  });
  const registerUser = useAuthStore((s) => s.register);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setServerError(null);
    setFieldErrors({});

    const parsed = registerSchema.safeParse(values);
    if (!parsed.success) {
      const errs: Partial<Record<keyof RegisterFormValues, string>> = {};
      for (const issue of parsed.error.issues) {
        const k = issue.path[0] as keyof RegisterFormValues;
        errs[k] = issue.message;
      }
      setFieldErrors(errs);
      return;
    }

    try {
      await registerUser(parsed.data);
      onSuccess();
    } catch (err) {
      setServerError(parseServerError(err));
    }
  };

  return (
    <form className="space-y-5" onSubmit={onSubmit} noValidate>
      <ServerErrorBanner message={serverError} />

      <FormField label="用户名" error={fieldErrors.username}>
        <input
          type="text"
          placeholder="2-64 位字母/数字/下划线"
          autoComplete="username"
          value={values.username}
          onChange={(e) =>
            setValues((v) => ({ ...v, username: e.target.value }))
          }
          className={cn(
            inputClass,
            fieldErrors.username
              ? "border-error focus:border-error focus:ring-error/20"
              : "border-outline-variant focus:border-primary focus:ring-primary/20",
          )}
        />
      </FormField>

      <FormField label="密码" error={fieldErrors.password}>
        <input
          type="password"
          placeholder="至少 6 位字符"
          autoComplete="new-password"
          value={values.password}
          onChange={(e) =>
            setValues((v) => ({ ...v, password: e.target.value }))
          }
          className={cn(
            inputClass,
            fieldErrors.password
              ? "border-error focus:border-error focus:ring-error/20"
              : "border-outline-variant focus:border-primary focus:ring-primary/20",
          )}
        />
      </FormField>

      <button
        type="submit"
        disabled={isSubmitting}
        className="bg-primary text-on-primary shadow-primary/10 mt-2 h-11 w-full rounded-lg font-semibold shadow-md transition-all hover:bg-primary-container active:scale-[0.98] disabled:opacity-60"
      >
        {isSubmitting ? "注册中..." : "创建账户"}
      </button>

      <p className="text-outline text-center text-[10px] leading-tight">
        点击注册即表示您同意我们的{" "}
        <a className="text-primary hover:underline" href="#">
          服务条款
        </a>{" "}
        和{" "}
        <a className="text-primary hover:underline" href="#">
          隐私政策
        </a>
      </p>
    </form>
  );
}

/** 服务端错误横条 */
function ServerErrorBanner({ message }: { readonly message: string | null }) {
  if (!message) return null;
  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-error-container text-on-error-container flex items-start gap-2 rounded-lg px-4 py-3 text-sm"
    >
      <MaterialSymbol name="error" size={18} />
      <span>{message}</span>
    </motion.div>
  );
}

/** 第三方登录 + 切换链接 */
function SocialAuthSection({
  mode,
  onSwitchMode,
}: {
  readonly mode: "login" | "register";
  readonly onSwitchMode: (m: "login" | "register") => void;
}) {
  return (
    <div className="mt-8 border-t border-outline-variant/50 pt-6">
      <div className="mb-6 flex items-center gap-3">
        <div className="bg-outline-variant h-px flex-1" />
        <span className="text-outline font-label-sm text-xs">第三方登录</span>
        <div className="bg-outline-variant h-px flex-1" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <SocialButton name="GitHub" icon="cloud" />
        <SocialButton name="SSO" icon="fingerprint" />
      </div>
      <p className="text-on-surface-variant mt-6 text-center text-sm">
        {mode === "login" ? "还没有账号？" : "已经有账号了？"}{" "}
        <button
          type="button"
          onClick={() => onSwitchMode(mode === "login" ? "register" : "login")}
          className="text-primary font-semibold hover:underline"
        >
          {mode === "login" ? "立即注册" : "回到登录"}
        </button>
      </p>
    </div>
  );
}

/** 第三方登录按钮 */
function SocialButton({
  name,
  icon,
}: {
  readonly name: string;
  readonly icon: string;
}) {
  return (
    <button
      type="button"
      className="bg-surface-container-low hover:bg-surface-container-high border-outline-variant flex h-10 items-center justify-center gap-2 rounded-lg border text-sm font-medium transition-colors"
    >
      <MaterialSymbol name={icon} size={18} />
      <span>{name}</span>
    </button>
  );
}

/* ====================== 工具函数 ====================== */

/** 把 axios 错误转成中文友好提示 */
function parseServerError(err: unknown): string {
  if (err instanceof AxiosError) {
    const status = err.response?.status;
    if (status === 409) return "该用户名已被占用,请更换一个";
    if (status === 401) return "用户名或密码错误";
    if (status === 422) return "请检查输入内容是否符合要求";
    if (status && status >= 500) return "服务暂时不可用,请稍后重试";
  }
  const e = toApiError(err);
  return e.message || "操作失败,请稍后重试";
}
