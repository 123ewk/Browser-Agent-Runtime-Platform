/**
 * 偏好模块类型定义 —— 与后端 schema/user_preference.py 严格对齐
 *
 * 后端端点:
 * - GET  /preferences: 全量返回用户偏好
 * - POST /preferences: 创建/更新偏好(upsert on key)
 * - POST /preferences/remember: 自然语言 → LLM 压缩 → 写入偏好
 * - DELETE /preferences/:id: 删除偏好
 */

/** 偏好分类 */
export type PreferenceCategory = "PREFERENCE" | "BEHAVIOR" | "INSTRUCTION";

/** 偏好来源 */
export type PreferenceSource = "EXPLICIT" | "IMPLICIT";

/** 创建/更新偏好请求体 */
export interface PreferenceCreatePayload {
  readonly key: string;
  readonly content: string;
  readonly category?: PreferenceCategory;
  readonly source?: PreferenceSource;
}

/** 偏好出参 —— 与后端 PreferenceOut 对齐 */
export interface PreferenceOut {
  readonly id: string;
  readonly user_id: string;
  readonly key: string;
  readonly content: string;
  readonly category: string;
  readonly source: string;
  readonly confidence: number;
  readonly mention_count: number;
  readonly created_at: string;
  readonly updated_at: string;
}

/** /remember 请求体 */
export interface RememberRequestPayload {
  readonly content: string;
}

/** /remember 响应 */
export interface RememberResponse {
  readonly extracted: readonly PreferenceOut[];
}
