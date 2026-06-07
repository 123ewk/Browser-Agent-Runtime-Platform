import { redirect } from "next/navigation";

/**
 * 根路由 —— 直接重定向到 Dashboard
 *
 * 避免出现"裸"/" 状态;后续可在 layout 拿登录态做权限门。
 */
export default function HomePage(): never {
  redirect("/dashboard");
}
