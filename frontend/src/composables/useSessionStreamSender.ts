/**
 * 复用逻辑层：封装流式发送 + 消息状态管理，供招投标 / 测评核查工作台复用。
 *
 * - 与业务无关：不关心是招投标还是测评核查，只按 SSE 事件回填消息与任务状态；
 * - messages：响应式消息列表（含占位 AI 消息，isStreaming 控制打字动画）；
 * - currentTask：task_created 事件写入的当前会话任务信息（intentType + taskId）；
 * - hitlQueue：hitl 事件写入的待审核任务队列，供页面层渲染审核面板；
 * - isSending：发送锁，防止连续发送；abort()：中断当前流式请求。
 */

import { reactive, ref } from 'vue'
import type { RagSource } from '@/types/chat'
import type { TopologyData } from '@/types/topology'
import {
  resumeChat,
  streamChat,
  type HitlPayload,
  type StreamChatParams,
  type ToolCallPayload,
} from '@/utils/streamChat'

/** 流式消息（页面层可映射为 ChatMessage 渲染） */
export interface StreamMessage {
  id: number
  role: 0 | 1
  content: string
  tool_calls?: ToolCallPayload[] | null
  file_extracted_text?: string | null
  /** 知识问答引用来源（done 事件回填 / 历史消息透传） */
  sources?: RagSource[] | null
  isStreaming: boolean
  taskId?: unknown
  intentType?: number
  created_at: number
}

/** 自检审核恢复参数（task_type=3）：approved 决定通过/驳回，modified_sections 供"修改后通过" */
export interface SelfcheckReviewOptions {
  approved: boolean
  modified_sections?: Record<string, unknown>
}

/** 发送目标会话（工作台页面向此结构传入） */
export interface WorkSession {
  id: number
  intent_type: number
}

/** 文件附件上下文（上传招标/投标文件后发送消息时携带） */
export interface StreamFileContext {
  upload_purpose?: number // 1=招标文件，5=投标文件
  file_path?: string
  file_extracted_text?: string
}

/** 当前会话任务信息（task_created 事件） */
export interface CurrentTask {
  intentType: number
  taskId: unknown
}

export function useSessionStreamSender() {
  const messages = ref<StreamMessage[]>([])
  const isSending = ref(false)
  const currentTask = ref<CurrentTask | null>(null)
  const hitlQueue = ref<HitlPayload[]>([])
  let controller: AbortController | null = null
  let seq = 0

  /** 重置本地状态（切换 / 新建会话时调用） */
  function reset() {
    abort()
    messages.value = []
    currentTask.value = null
    hitlQueue.value = []
    isSending.value = false
  }

  /** 中断当前流式请求（占位消息保留已拼内容） */
  function abort() {
    controller?.abort()
    controller = null
  }

  /**
   * 发送一条消息：立即展示用户消息 + AI 占位空消息（打字动画），
   * 流式回填 content / tool_calls，流结束后 isStreaming=false。
   * fileContext：文件附件场景（上传招标/投标文件后发送），随请求体传给后端识别上传用途。
   */
  async function sendMessage(
    content: string,
    session: WorkSession,
    fileContext?: StreamFileContext,
    onTopology?: (data: TopologyData) => void,
  ): Promise<void> {
    const text = content.trim()
    if (!text || isSending.value) return

    const now = Math.floor(Date.now() / 1000)
    seq += 1
    messages.value.push({
      id: seq,
      role: 0,
      content: text,
      tool_calls: null,
      file_extracted_text: fileContext?.file_extracted_text ?? null,
      isStreaming: false,
      intentType: session.intent_type,
      created_at: now,
    })
    // 关键：aiMessage 必须用 reactive 包装后再推入 ref 数组。
    // 若推入裸对象，Vue 仅在“读取”时返回代理（toReactive 缓存），
    // 后续 onToken/finally 直接改裸对象属性不经过代理 → 不触发响应式 → 界面不更新。
    const aiMessage: StreamMessage = reactive({
      id: -seq,
      role: 1,
      content: '',
      tool_calls: null,
      file_extracted_text: null,
      sources: null,
      isStreaming: true,
      intentType: session.intent_type,
      created_at: now,
    })
    messages.value.push(aiMessage)

    isSending.value = true
    controller = new AbortController()

    const params: StreamChatParams = {
      session_id: session.id,
      content: text,
      role: 0,
      intent_type: session.intent_type,
      ...(fileContext ?? {}),
    }

    try {
      await streamChat(params, {
        signal: controller.signal,
        onToken: (piece) => {
          aiMessage.content += piece
        },
        onToolCall: (payload) => {
          aiMessage.tool_calls = [...(aiMessage.tool_calls ?? []), payload]
        },
        onTaskCreated: (payload) => {
          currentTask.value = { intentType: payload.intent_type, taskId: payload.task_id }
        },
        onHitl: (payload) => {
          hitlQueue.value.push(payload)
        },
        onTopology,
        onDone: (payload) => {
          // 知识问答（intent=3）：done 事件带完整引用来源
          aiMessage.sources = payload?.sources ?? null
        },
        onError: (message) => {
          aiMessage.content = aiMessage.content
            ? `${aiMessage.content}\n\n（错误：${message}）`
            : `（错误：${message}）`
        },
      })
    } finally {
      aiMessage.isStreaming = false
      isSending.value = false
      controller = null
    }
  }

  /**
   * 恢复 HITL 中断的招投标对话（解析结果确认 task_type=2 / 自检审核 task_type=3）。
   * 从 hitlPayload 取 thread_id 调 resumeChat，token 流式追加到新的 AI 占位消息；
   * 自检审核驳回后图重新生成并再次中断，resume 流中会推送新一轮 hitl 事件，
   * 通过 onHitl 回调继续入队（旧任务在流结束后从 hitlQueue 移除，天然防重复审核）。
   */
  async function resumeHitl(
    payload: HitlPayload,
    session: WorkSession,
    options?: SelfcheckReviewOptions,
  ): Promise<void> {
    if (!payload.thread_id || isSending.value) return

    const now = Math.floor(Date.now() / 1000)
    seq += 1
    const aiMessage: StreamMessage = reactive({
      id: -seq,
      role: 1,
      content: '',
      tool_calls: null,
      file_extracted_text: null,
      sources: null,
      isStreaming: true,
      intentType: session.intent_type,
      created_at: now,
    })
    messages.value.push(aiMessage)

    isSending.value = true
    controller = new AbortController()
    try {
      await resumeChat(
        payload.thread_id,
        {
          session_id: session.id,
          review_type: payload.task_type === 3 ? 'selfcheck_review' : 'parsed_review',
          confirmed: true,
          approved: options?.approved,
          modified_sections: options?.modified_sections,
        },
        {
          signal: controller.signal,
          onToken: (piece) => {
            aiMessage.content += piece
          },
          onHitl: (next) => {
            hitlQueue.value.push(next)
          },
          onError: (message) => {
            aiMessage.content = aiMessage.content
              ? `${aiMessage.content}\n\n（错误：${message}）`
              : `（错误：${message}）`
          },
        },
      )
    } finally {
      aiMessage.isStreaming = false
      isSending.value = false
      controller = null
      hitlQueue.value = hitlQueue.value.filter((h) => h !== payload)
    }
  }

  return { messages, isSending, currentTask, hitlQueue, sendMessage, resumeHitl, abort, reset }
}
