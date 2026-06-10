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

/** 任务控制动作响应(对齐后端 TaskActionResponse) */
export interface TaskActionResponse {
  readonly task_id: string;
  readonly state: TaskStatus;
  readonly accepted: boolean;
  readonly reason: string;
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

/** POST /tasks/:id/stop —— 停止任务(转 CANCELLED)

 2026-06-10 新增,作为前端第三个逃生通道:
 - 「+ 新建任务」:清空 activeTaskId,跳出当前任务
 - 「停止任务」:终止任务,转 CANCELLED(终态),释放 Worker
 - 「暂停任务」:转 PAUSED,V1 Worker 退出但状态保留(resume 是 V2)

 三个动作可在任意时刻触发,允许用户从"任务卡死"场景中走出。
 */
export async function stopTask(taskId: string): Promise<TaskActionResponse> {
  const { data } = await apiClient.post<TaskActionResponse>(
    `/tasks/${taskId}/stop`,
  );
  return data;
}

/** POST /tasks/:id/pause —— 暂停任务(转 PAUSED) */
export async function pauseTask(taskId: string): Promise<TaskActionResponse> {
  const { data } = await apiClient.post<TaskActionResponse>(
    `/tasks/${taskId}/pause`,
  );
  return data;
}

/** POST /tasks/:id/resume —— 继续任务(PAUSED → RUNNING) */
export async function resumeTask(taskId: string): Promise<TaskActionResponse> {
  const { data } = await apiClient.post<TaskActionResponse>(
    `/tasks/${taskId}/resume`,
  );
  return data;
}
