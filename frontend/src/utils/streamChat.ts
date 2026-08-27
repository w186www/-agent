/**
 * 流式聊天 API 层：只负责请求与 SSE 解析，不做任何 UI 状态管理。
 *
 * - 使用 fetch 发送 POST /chat/stream（JSON body：session_id/content/role/intent_type）；
 * - 手动解析 SSE 流（ReadableStream + TextDecoder），按 `data: ` 前缀逐行解析事件；
 * - 事件类型约定（与后端 chat_stream.py 对齐）：
 *   - token：流式文本片段，content 为增量文本；
 *   - tool_call：payload 含 tool_name/arguments/result/duration_ms；
 *   - task_created：payload 含 intent_type/task_id；
 *   - hitl：payload 含 review_task_id/task_type/source_type/source_id/review_data；
 *   - done：流结束，调用 onClose；error：payload.message 为错误信息，调用 onError。
 */

import { BASE_URL } from './request'
import type { RagSource } from '@/types/chat'
import type { TopologyData } from '@/types/topology'

export interface StreamChatParams {
  session_id: number
  content: string
  role: number // 0=user
  intent_type: number // 0=对话助手，1=招投标，2=测评核查，3=知识问答
  // 文件附件场景（用户上传招标/投标文件后发送消息，intent_type=1 时后端识别上传用途）
  upload_purpose?: number // 1=招标文件，5=投标文件
  file_path?: string // 上传文件存储路径（minio://...）
  file_extracted_text?: string // 上传文件提取的文本（供对话上下文）
}

/** tool_call 事件载荷 */
export interface ToolCallPayload {
  tool_name: string
  arguments?: Record<string, unknown>
  result?: unknown
  duration_ms?: number
}

/** task_created 事件载荷：task_id 为 {id,status}（招投标）或控制点摘要列表（测评核查） */
export interface TaskCreatedPayload {
  intent_type: number
  task_id: unknown
}

/** hitl 事件载荷：人工介入审核任务 */
export interface HitlPayload {
  review_task_id: number
  task_type: number // 0=审核（报价/自检/投标文件），1=低置信度复核，2=解析结果确认，3=自检审核
  source_type: number // 0=BiddingTask，1=AssessmentRecord
  source_id: number
  thread_id?: string // 招投标 HITL 中断的 thread_id，供 resume 恢复图执行
  review_data: Record<string, unknown>
}

/** resume 请求参数：恢复 HITL 中断的招投标对话 */
export interface ResumeChatParams {
  session_id: number
  review_type: 'parsed_review' | 'selfcheck_review' // 第一个/第二个 HITL 恢复场景
  confirmed: boolean
  approved?: boolean // selfcheck_review：审核是否通过（False=驳回重新生成）
  modified_sections?: Record<string, unknown> // selfcheck_review：修改后通过的投标内容
}

/** done 事件载荷：知识问答（intent=3）带完整引用来源 */
export interface DonePayload {
  session_id: number
  sources?: RagSource[]
}

/** topology 事件载荷：Agent 生成的网络拓扑图数据 */
export interface TopologyPayload {
  topology_data: TopologyData
}

export type StreamEvent =
  | { type: 'token'; content: string }
  | { type: 'tool_call'; payload: ToolCallPayload }
  | { type: 'task_created'; payload: TaskCreatedPayload }
  | { type: 'hitl'; payload: HitlPayload }
  | { type: 'topology'; payload: TopologyPayload }
  | { type: 'done'; payload?: DonePayload }
  | { type: 'error'; payload: { message: string } }

export interface StreamChatOptions {
  onToken?: (content: string) => void
  onToolCall?: (payload: ToolCallPayload) => void
  onTaskCreated?: (payload: TaskCreatedPayload) => void
  onHitl?: (payload: HitlPayload) => void
  onTopology?: (data: TopologyData) => void
  onDone?: (payload?: DonePayload) => void
  onError?: (message: string) => void
  onClose?: () => void
  signal?: AbortSignal
}

/** 解析单个 data: 行并分发给对应回调 */
function dispatchEvent(event: StreamEvent, options: StreamChatOptions): boolean {
  switch (event.type) {
    case 'token':
      options.onToken?.(event.content)
      break
    case 'tool_call':
      options.onToolCall?.(event.payload)
      break
    case 'task_created':
      options.onTaskCreated?.(event.payload)
      break
    case 'hitl':
      options.onHitl?.(event.payload)
      break
    case 'topology':
      options.onTopology?.(event.payload.topology_data)
      break
    case 'done':
      options.onDone?.(event.payload)
      break
    case 'error':
      options.onError?.(event.payload.message)
      break
  }
  // done / error 均视为流结束（error 已单独回调）
  return event.type === 'done' || event.type === 'error'
}

/** 读取 SSE 流并按事件类型分发回调（token/tool_call/task_created/hitl/error）。 */
async function readSSEStream(resp: Response, options: StreamChatOptions): Promise<void> {
  const reader = resp.body!.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // SSE 事件以空行分隔，逐个取出解析
      let sepIdx: number
      while ((sepIdx = buffer.indexOf('\n\n')) >= 0) {
        const raw = buffer.slice(0, sepIdx)
        buffer = buffer.slice(sepIdx + 2)
        const dataLine = raw.split('\n').find((line) => line.startsWith('data: '))
        if (!dataLine) continue
        try {
          const event = JSON.parse(dataLine.slice('data: '.length)) as StreamEvent
          if (dispatchEvent(event, options)) return
        } catch {
          /* 忽略无法解析的行 */
        }
      }
    }
  } catch (err) {
    if (options.signal?.aborted) return
    throw err
  } finally {
    reader.releaseLock()
  }
  options.onClose?.()
}

/**
 * 发起流式聊天请求。
 * 正常结束（done/error/网络完成）时 resolve；用户主动 abort 时不抛错、正常返回。
 */
export async function streamChat(
  params: StreamChatParams,
  options: StreamChatOptions = {},
): Promise<void> {
  const token = localStorage.getItem('access_token')
  let resp: Response
  try {
    resp = await fetch(`${BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(params),
      signal: options.signal,
    })
  } catch (err) {
    // 主动中断：静默结束，交由调用方收尾
    if (options.signal?.aborted) {
      options.onClose?.()
      return
    }
    throw err
  }

  if (!resp.ok || !resp.body) {
    let message = `请求失败（HTTP ${resp.status}）`
    try {
      const data = await resp.json()
      message = data?.message || data?.detail || message
    } catch {
      /* 非 JSON 错误体，保留默认提示 */
    }
    options.onError?.(message)
    options.onClose?.()
    return
  }

  await readSSEStream(resp, options)
}

/**
 * 恢复 HITL 中断的招投标对话（POST /chat/{thread_id}/resume）。
 * 后端恢复图执行后推送 token/done/error 事件，解析逻辑与 streamChat 复用。
 */
export async function resumeChat(
  threadId: string,
  params: ResumeChatParams,
  options: StreamChatOptions = {},
): Promise<void> {
  const token = localStorage.getItem('access_token')
  let resp: Response
  try {
    resp = await fetch(`${BASE_URL}/chat/${threadId}/resume`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(params),
      signal: options.signal,
    })
  } catch (err) {
    // 主动中断：静默结束，交由调用方收尾
    if (options.signal?.aborted) {
      options.onClose?.()
      return
    }
    throw err
  }

  if (!resp.ok || !resp.body) {
    let message = `恢复失败（HTTP ${resp.status}）`
    try {
      const data = await resp.json()
      message = data?.message || data?.detail || message
    } catch {
      /* 非 JSON 错误体，保留默认提示 */
    }
    options.onError?.(message)
    options.onClose?.()
    return
  }

  await readSSEStream(resp, options)
}
