import type { TaskDetail, TaskSummary, TaskStatus } from "@/types/task";
import type { Paginated } from "@/types/api";
import type { CreateTaskRequest, CreateTaskResponse } from "@/types/chat";
import { apiClient } from "./client";

/** 任务列表查询参数 */
export interface ListTasksParams {
  readonly page?: number;
  readonly pageSize?: number;
  readonly status?: TaskStatus;
  readonly search?: string;
}

/** GET /tasks —— 任务中心表格 */
export async function listTasks(
  params: ListTasksParams = {},
): Promise<Paginated<TaskSummary>> {
  const { data } = await apiClient.get<Paginated<TaskSummary>>("/tasks", {
    params,
  });
  return data;
}

/** GET /tasks/:id —— 任务详情 */
export async function getTask(id: string): Promise<TaskDetail> {
  const { data } = await apiClient.get<TaskDetail>(`/tasks/${id}`);
  return data;
}

/** POST /tasks —— 创建浏览器任务 */
export async function createTask(goal: string): Promise<CreateTaskResponse> {
  const { data } = await apiClient.post<CreateTaskResponse>("/tasks", {
    goal,
  } as CreateTaskRequest);
  return data;
}
