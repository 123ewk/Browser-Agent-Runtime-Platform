import type { TaskDetail, TaskSummary, TaskStatus } from "@/types/task";
import type { Paginated } from "@/types/api";
import { apiClient } from "./client";

/** 任务列表查询参数 */
export interface ListTasksParams {
  readonly page?: number;
  readonly pageSize?: number;
  readonly status?: TaskStatus;
  readonly search?: string;
}

/** GET /api/tasks —— 任务中心表格 */
export async function listTasks(
  params: ListTasksParams = {},
): Promise<Paginated<TaskSummary>> {
  const { data } = await apiClient.get<Paginated<TaskSummary>>("/api/tasks", {
    params,
  });
  return data;
}

/** GET /api/tasks/:id —— 任务详情 */
export async function getTask(id: string): Promise<TaskDetail> {
  const { data } = await apiClient.get<TaskDetail>(`/api/tasks/${id}`);
  return data;
}
