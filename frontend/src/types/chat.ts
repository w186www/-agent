/** 会话 / 消息 / 工具调用 / 任务卡片相关类型定义 */

export interface ToolCall {
  name: string
  arguments?: Record<string, unknown>
  result?: unknown
  duration_ms?: number
}

export interface Conversation {
  id: number
  title: string
  role_type: number // 0=商务，1=技术
  intent_type: number // 0=对话助手，1=招投标，2=测评核查，3=知识问答
  created_at: number
  updated_at: number
  /** 会话级绑定附件文件名（对话/知识问答附件，发送消息自动携带） */
  attachment_name?: string | null
  active?: boolean
}

/** RAG 回答引用来源（SSE done 与历史消息回显共用；切片已删除时 text 为提示文案） */
export interface RagSource {
  chunk_id: number | null
  resource_id: number | null
  chunk_index: number | null
  file_name: string | null
  score: number | null
  text: string
}

export interface ChatMessage {
  id: number
  role: 0 | 1 // 0=user，1=assistant
  content: string
  tool_calls?: ToolCall[] | null
  file_name?: string | null
  file_extracted_text?: string | null
  /** 知识问答引用来源（历史消息接口回查重拼；流式 done 事件直接返回完整结构） */
  sources?: RagSource[] | null
  created_at: number
  /** 会话意图类型与任务卡片数据（接口按会话补齐） */
  intent_type?: number // 0=对话助手，1=招投标，2=测评核查，3=知识问答
  task_id?: unknown // intent=1 为 {id,status}；intent=2 为控制点摘要列表；0/3 为 null
  /** 本地状态：流式输出中显示打字动画 */
  loading?: boolean
}

/** 消息分页响应：before_id 为下一页游标（取返回首条消息 id） */
export interface MessagePage {
  items: ChatMessage[]
  has_more: boolean
  before_id: number | null
}

export interface SessionPage {
  items: Conversation[]
  total: number
  page: number
  page_size: number
}

/** 竞标流程阶段（bidding_tasks.status 0-5） */
export const BIDDING_STAGES = [
  { status: 0, label: '搜索中' },
  { status: 1, label: '已解析' },
  { status: 2, label: '编写中' },
  { status: 3, label: '废标检查中' },
  { status: 4, label: '待人工审核' },
  { status: 5, label: '已完成' },
] as const

/** 废标检查结果项：item/type/status/detail（status 映射 pass/warning/danger 三色） */
export interface ComplianceItem {
  item: string
  type?: string
  status: 'pass' | 'warning' | 'danger'
  detail?: string
}

export interface BiddingTask {
  id: number
  session_id: number
  tender_title?: string | null
  tender_url?: string | null
  tender_file_path?: string | null
  bidding_sections?: Record<string, string> | null
  compliance_result?: ComplianceItem[] | null
  reference_doc_ids?: number[] | null
  status: number
  created_at: number
  updated_at: number
}

/** 测评核查状态（assessment_records.status 0-6） */
export const ASSESSMENT_STAGES = [
  { status: 0, label: '待测评' },
  { status: 1, label: '待核查' },
  { status: 2, label: '核查中' },
  { status: 3, label: '自动通过' },
  { status: 4, label: '待人工复核' },
  { status: 5, label: '已确认' },
  { status: 6, label: '异常' },
] as const

export interface AssessmentRecord {
  id: number
  session_id: number
  system_level: number
  checklist_code: string
  checklist_name: string
  assessment_command?: string | null
  screenshot_path?: string | null
  vlm_analysis?: Record<string, unknown> | null
  human_record?: string | null
  comparison_result?: Record<string, unknown> | null
  kb_references?: Array<Record<string, unknown>> | null
  confidence: number
  status: number
  created_at: number
}

/** 意图类型 -> 名称（新建会话弹窗用） */
export const INTENT_TYPES = [
  { value: 0, label: '对话助手' },
  { value: 1, label: '招投标' },
  { value: 2, label: '测评核查' },
  { value: 3, label: '知识问答' },
] as const
