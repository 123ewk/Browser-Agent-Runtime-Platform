/**
 * Vitest 启动前的全局 setup
 *
 * - 引入 @testing-library/jest-dom 扩展 expect 断言
 *   (后续可用 toBeInTheDocument / toHaveClass 等)
 * - 加载 .env 测试环境变量(目前不区分 dev/test,留接口)
 */
import "@testing-library/jest-dom/vitest";
