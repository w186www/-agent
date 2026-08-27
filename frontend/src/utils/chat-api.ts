/**
 * 会话 / 消息 / 招投标 / 测评核查 API 封装。
 * 响应结构统一为 ApiResponse（data 为业务数据）。
 */

import request from './request'
import type {
  AssessmentRecord,
  BiddingTask,
  Conversation,
  MessagePage,
  SessionPage,
} from '@/types/chat'
import type { TopologyData } from '@/types/topology'

/** 会话列表（分页，可选按角色类型筛选） */
export function getSessionsApi(params: {
  page?: number
  page_size?: number
  role_type?: number
  intent_type?: number
}) {
  return request.get<{ data: SessionPage }>('/sessions', { params })
}

/** 新建会话 */
export function createSessionApi(data: { role_type: number; intent_type: number; title?: string }) {
  return request.post<{ data: Conversation }>('/sessions', data)
}

/** 编辑会话标题 */
export function updateSessionApi(sessionId: number, data: { title: string }) {
  return request.put<{ data: Conversation }>(`/sessions/${sessionId}`, data)
}

/** 删除会话 */
export function deleteSessionApi(sessionId: number) {
  return request.delete<{ data: null }>(`/sessions/${sessionId}`)
}

/** 清空会话绑定附件（移除后后续消息不再自动携带该附件内容） */
export function clearSessionAttachmentApi(sessionId: number) {
  return request.post<{ data: null }>(`/sessions/${sessionId}/attachment/clear`)
}

/** 按会话分页查询消息（before_id 游标向前翻页） */
export function getMessagesApi(
  sessionId: number,
  params: { before_id?: number | null; limit?: number },
) {
  return request.get<{ data: MessagePage }>(`/sessions/${sessionId}/messages`, { params })
}

/** 查询会话下最新招投标任务（无则 data=null） */
export function getBiddingTasksApi(sessionId: number) {
  return request.get<{ data: BiddingTask | null }>('/bidding_tasks', { params: { session_id: sessionId } })
}

/** 查询会话最新生成的网络拓扑（无则 data=null） */
export function getSessionTopologyApi(sessionId: number) {
  return request.get<{ data: TopologyData | null }>(`/sessions/${sessionId}/topology`)
}

/** 招投标任务详情 */
export function getBiddingTaskApi(taskId: number) {
  return request.get<{ data: BiddingTask }>(`/bidding_tasks/${taskId}`)
}

/** 按会话查询测评核查记录列表 */
export function getAssessmentRecordsApi(sessionId: number) {
  return request.get<{ data: { items: AssessmentRecord[] } }>('/assessment_records', {
    params: { session_id: sessionId },
  })
}

/** 测评核查记录详情 */
export function getAssessmentRecordApi(recordId: number) {
  return request.get<{ data: AssessmentRecord }>(`/assessment_records/${recordId}`)
}

/** 触发测评清单生成（LLM 按等保级别生成控制点清单并写入 assessment_records） */
export function generateChecklistApi(data: {
  session_id: number
  system_level?: number // 0=二级，1=三级，2=四级
  system_name?: string
}) {
  return request.post<{ data: { items: AssessmentRecord[]; total_count: number } }>(
    '/assessment/generate_checklist',
    data,
  )
}

/** 上传测评截图并触发 VLM 分析（上传后若已有人工记录则自动比对） */
export async function uploadScreenshotApi(
  recordId: number,
  file: File,
): Promise<{
  record_id: number
  status: number
  vlm_analysis: Record<string, unknown>
  comparison_done: boolean
  confidence: number
  review_task_id: number | null
}> {
  const form = new FormData()
  form.append('file', file)
  const res = await request.post<{
    data: {
      record_id: number
      status: number
      vlm_analysis: Record<string, unknown>
      comparison_done: boolean
      confidence: number
      review_task_id: number | null
    }
  }>(`/assessment/${recordId}/upload_screenshot`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data.data
}

/** 提交人工记录；若已有 VLM 分析结果则自动触发比对 */
export function submitHumanRecordApi(recordId: number, humanRecord: string) {
  return request.put<{
    data: {
      record_id: number
      status: number
      confidence: number
      comparison_done: boolean
      comparison_result: Record<string, unknown> | null
      review_task_id: number | null
    }
  }>(`/assessment/${recordId}/human_record`, { human_record: humanRecord })
}

/** 提交人工审核结果（HITL）：approve=通过，reject=驳回，modified=修改后通过 */
export function submitReviewApi(
  reviewTaskId: number,
  data: { action: 'approve' | 'reject' | 'modified'; comment?: string },
) {
  return request.post<{ data: unknown }>(`/review/${reviewTaskId}`, data)
}

/** 审核任务摘要（GET /review 列表项） */
export interface ReviewSummary {
  review_task_id: number
  task_type: number // 0=审核（报价/自检/投标文件），1=低置信度复核，2=解析结果确认，3=自检审核
  source_type: number
  source_id: number
  category: string
  title: string
  summary: unknown
  confidence: string
  created_at: number
}

/** 审核任务详情（GET /review/{id}） */
export interface ReviewDetail {
  review_task_id: number
  task_type: number
  source_type: number
  source_id: number
  review_data: Record<string, unknown>
  review_result: number | null // 0=通过，1=驳回，2=修改后通过
  review_comment: string | null
  reviewer: { username: string; display_name: string } | null
  status: number
  created_at: number
  reviewed_at: number | null
}

/** 审核任务列表（按 task_type 分组；status=0 待审核，1 已审核；sessionId 非空时仅返回该测评项目） */
export function getReviewsApi(status = 0, sessionId?: number) {
  return request.get<{ data: { status: number; total: number; groups: Record<number, ReviewSummary[]> } }>(
    '/review',
    { params: { status, session_id: sessionId ?? undefined } },
  )
}

/** 审核任务详情 */
export function getReviewDetailApi(reviewTaskId: number) {
  return request.get<{ data: ReviewDetail }>(`/review/${reviewTaskId}`)
}

/** 上传文件返回结构（后端 upload_service_minio 常规存储） */
export interface UploadResult {
  type: 'image' | 'document'
  path: string | null
  filename: string
  size: number
  original_name: string
  resource_id?: number
  deduplicated?: boolean
  expire_time?: number | null
  extracted_text?: string
}

/** 通用文件上传（multipart/form-data），upload_purpose=3 时后端自动关联测评核查记录截图 */
export async function uploadFileApi(
  file: File,
  options: { upload_purpose?: number; storage_scene?: number; session_id?: number } = {},
): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('upload_purpose', String(options.upload_purpose ?? 0))
  form.append('storage_scene', String(options.storage_scene ?? 0))
  if (options.session_id !== undefined) {
    form.append('session_id', String(options.session_id))
  }
  const res = await request.post<{ data: UploadResult }>('/upload/file', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data.data
}

/** 获取或创建指定意图的会话：优先复用最近一条同意图会话，否则新建 */
export async function getOrCreateIntentSession(
  intentType: number,
  roleType: number,
): Promise<Conversation> {
  const res = await getSessionsApi({ page: 1, page_size: 20, role_type: roleType })
  const found = res.data.data.items.find((s) => s.intent_type === intentType)
  if (found) return found
  const created = await createSessionApi({ role_type: roleType, intent_type: intentType })
  return created.data.data
}
