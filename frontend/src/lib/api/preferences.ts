import { apiClient } from "./client";
import type {
  PreferenceCreatePayload,
  PreferenceOut,
  RememberRequestPayload,
  RememberResponse,
} from "@/types/preference";

/**
 * 偏好 API 调用层 —— 与后端 /preferences/* 端点对应
 *
 * 后端实现:
 * - GET  /preferences: 200 + 偏好列表
 * - POST /preferences: 201 + PreferenceOut(upsert on user_id+key)
 * - POST /preferences/remember: 200 + RememberResponse
 * - DELETE /preferences/:id: 204
 */

/** GET /preferences —— 全量返回当前用户偏好 */
export async function listPreferences(): Promise<readonly PreferenceOut[]> {
  const { data } = await apiClient.get<readonly PreferenceOut[]>("/preferences");
  return data;
}

/** POST /preferences —— 创建/更新偏好(upsert on key) */
export async function createPreference(
  payload: PreferenceCreatePayload,
): Promise<PreferenceOut> {
  const { data } = await apiClient.post<PreferenceOut>("/preferences", payload);
  return data;
}

/** DELETE /preferences/:id —— 删除偏好 */
export async function deletePreference(prefId: string): Promise<void> {
  await apiClient.delete(`/preferences/${prefId}`);
}

/** POST /preferences/remember —— 自然语言 → LLM 压缩 → 写入偏好 */
export async function rememberPreference(
  payload: RememberRequestPayload,
): Promise<RememberResponse> {
  const { data } = await apiClient.post<RememberResponse>(
    "/preferences/remember",
    payload,
  );
  return data;
}
