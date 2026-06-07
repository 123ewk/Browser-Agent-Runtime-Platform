/**
 * API 通用响应壳 —— 镜像后端 Pydantic 的 `{ data, error }` 风格
 *
 * 后端目前用 FastAPI 直接返回数据,这里预留包装壳以便后续
 * 接入 BFF 层时保持类型兼容;同时定义分页/错误两种基础类型。
 */

export interface ApiError {
  readonly code: string;
  readonly message: string;
  readonly details?: Readonly<Record<string, unknown>>;
}

export interface Paginated<T> {
  readonly items: readonly T[];
  readonly total: number;
  readonly page: number;
  readonly pageSize: number;
}
