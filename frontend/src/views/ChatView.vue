<script setup lang="ts">
import { ref, computed, nextTick, watch, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import type { ChatMessage, Conversation } from '@/types/chat'
import { INTENT_TYPES } from '@/types/chat'
import { useRole } from '@/stores/role'
import ConversationList from '@/components/chat/ConversationList.vue'
import MessageItem from '@/components/chat/MessageItem.vue'
import ChatInputBar from '@/components/chat/ChatInputBar.vue'
import BiddingTaskCard from '@/components/chat/BiddingTaskCard.vue'
import AssessmentTaskCard from '@/components/chat/AssessmentTaskCard.vue'
import BiddingReviewPanel from '@/components/chat/BiddingReviewPanel.vue'
import TopologyPanel from '@/components/topology/TopologyPanel.vue'
import type { TopologyData } from '@/types/topology'
import {
  clearSessionAttachmentApi,
  createSessionApi,
  getMessagesApi,
  getSessionTopologyApi,
  uploadFileApi,
} from '@/utils/chat-api'
import {
  useSessionStreamSender,
  type StreamFileContext,
  type StreamMessage,
  type WorkSession,
} from '@/composables/useSessionStreamSender'
import type { HitlPayload, ToolCallPayload } from '@/utils/streamChat'

const { role } = useRole()

// 角色类型：business=0（商务），tech=1（技术）
const roleType = computed(() => (role.value === 'business' ? 0 : 1))

// 新建会话弹窗按角色过滤意图：商务=对话/知识问答/招投标，技术=对话/知识问答/测评核查
const allowedIntentTypes = computed(() =>
  role.value === 'business' ? [0, 3, 1] : [0, 3, 2],
)

const activeSession = ref<Conversation | null>(null)
const messagesRef = ref<HTMLElement | null>(null)

/** 当前会话网络拓扑数据（进入会话时从历史加载，generate_topology 流式事件刷新） */
const currentTopology = ref<TopologyData | null>(null)

// ── 消息区：复用流式发送逻辑（历史分页 + 流式回填 + HITL 队列）──
const { messages, isSending, currentTask, hitlQueue, sendMessage, resumeHitl, abort, reset } =
  useSessionStreamSender()
const hasMore = ref(true)
const loading = ref(false)
const loadingOlder = ref(false)

const PAGE_LIMIT = 20

/** 招投标会话展示所需的最小会话结构 */
function toWorkSession(): WorkSession | null {
  if (!activeSession.value) return null
  return { id: activeSession.value.id, intent_type: activeSession.value.intent_type }
}

/** 服务端消息 -> 流式消息结构 */
function toStreamMessage(m: ChatMessage): StreamMessage {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    tool_calls: (m.tool_calls ?? null) as ToolCallPayload[] | null,
    file_extracted_text: m.file_extracted_text ?? null,
    sources: m.sources ?? null,
    isStreaming: false,
    taskId: m.task_id,
    intentType: m.intent_type,
    created_at: m.created_at,
  }
}

/** 流式消息 -> ChatMessage（tool_name 归一为 name，isStreaming 映射为 loading） */
const renderMessages = computed<ChatMessage[]>(() =>
  messages.value.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content,
    tool_calls: (m.tool_calls ?? []).map((c) => ({
      name: c.tool_name,
      arguments: c.arguments,
      result: c.result,
      duration_ms: c.duration_ms,
    })),
    file_extracted_text: m.file_extracted_text ?? null,
    sources: m.sources ?? null,
    created_at: m.created_at,
    loading: m.isStreaming,
    intent_type: m.intentType,
    task_id: m.taskId,
  })),
)

/** 切换会话：重置流式状态并加载最新一页消息 */
async function loadMessages(session: Conversation, scrollToBottom = true) {
  loading.value = true
  try {
    const res = await getMessagesApi(session.id, { before_id: null, limit: PAGE_LIMIT })
    reset()
    messages.value = res.data.data.items.map(toStreamMessage)
    hasMore.value = res.data.data.has_more
  } finally {
    loading.value = false
  }
  await loadSessionTopology(session.id)
  if (scrollToBottom) {
    await nextTick()
    scrollToBottomNow()
  }
}

/** 加载会话历史网络拓扑（无则清空） */
async function loadSessionTopology(sessionId: number) {
  try {
    const res = await getSessionTopologyApi(sessionId)
    currentTopology.value = res.data.data ?? null
  } catch {
    currentTopology.value = null
  }
}

/** 上拉翻页：距顶部 100px 触发，加载更早消息并保持滚动位置 */
async function loadOlder() {
  if (!activeSession.value || loadingOlder.value || !hasMore.value) return
  loadingOlder.value = true
  const el = messagesRef.value
  const prevHeight = el?.scrollHeight ?? 0
  const prevTop = el?.scrollTop ?? 0
  try {
    const res = await getMessagesApi(activeSession.value.id, {
      before_id: messages.value[0]?.id ?? null,
      limit: PAGE_LIMIT,
    })
    const page = res.data.data
    if (page.items.length) {
      messages.value = [...page.items.map(toStreamMessage), ...messages.value]
    }
    hasMore.value = page.has_more
    // 补偿新增内容高度，保持视口位置不动
    if (el && page.items.length) {
      await nextTick()
      el.scrollTop = el.scrollHeight - prevHeight + prevTop
    }
  } finally {
    loadingOlder.value = false
  }
}

function onMessagesScroll(e: Event) {
  const el = e.target as HTMLElement
  if (el.scrollTop < 100) {
    loadOlder()
  }
}

function scrollToBottomNow() {
  const el = messagesRef.value
  if (el) el.scrollTop = el.scrollHeight
}

// ── 会话选择 / 新建 / 删除 ──
function handleSelect(conv: Conversation | null) {
  if (!conv) {
    activeSession.value = null
    currentTopology.value = null
    reset()
    return
  }
  if (activeSession.value?.id === conv.id) return
  activeSession.value = conv
  loadMessages(conv)
}

function handleCreated(conv: Conversation) {
  activeSession.value = conv
  loadMessages(conv, false)
}

// ── 任务卡片：按 intent_type 显示 ──
const showBiddingCard = computed(() => activeSession.value?.intent_type === 1)
const showAssessmentCard = computed(() => activeSession.value?.intent_type === 2)

// ── 招投标流程步骤（intent=1 会话显示；status 0-6，含异常终止）──
const BIDDING_FLOW = [
  { status: 0, label: '搜索中' },
  { status: 1, label: '已解析' },
  { status: 2, label: '编写中' },
  { status: 3, label: '废标检查中' },
  { status: 4, label: '待人工审核' },
  { status: 5, label: '已完成' },
  { status: 6, label: '异常终止' },
]

/** 当前招投标状态（task_created 写入的 {id,status}；未流式时保持 0） */
const bidStatus = computed(() => {
  const t = currentTask.value?.taskId
  if (t && typeof t === 'object' && 'status' in (t as object)) {
    return (t as { status: number }).status
  }
  return 0
})

const steps = computed(() =>
  BIDDING_FLOW.map((step) => ({
    id: step.status + 1,
    label: step.label,
    status:
      bidStatus.value > step.status
        ? 'done'
        : bidStatus.value === step.status
          ? 'active'
          : 'pending',
  })) as { id: number; label: string; status: 'done' | 'active' | 'pending' }[],
)

// ── 文件上传：招投标文件（purpose=1/5）与对话附件（purpose=0 只提取文本）──
const inputDraft = ref('')
const pendingFile = ref<StreamFileContext | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

/** 触发招投标文件选择器：purpose=1 招标文件，5 投标文件 */
function triggerUpload(purpose: number) {
  if (!activeSession.value) return
  pendingFile.value = { upload_purpose: purpose }
  fileInputRef.value?.click()
}

/** 触发对话附件选择器（intent=0/3）：绑定到会话，发送时自动携带 */
function triggerAttachment() {
  if (!activeSession.value) {
    ElMessage.warning('请先选择或新建一个会话，再上传附件')
    return
  }
  pendingFile.value = { upload_purpose: 0 }
  fileInputRef.value?.click()
}

/** 移除会话绑定附件 */
async function handleClearAttachment() {
  const session = activeSession.value
  if (!session) return
  await clearSessionAttachmentApi(session.id)
  session.attachment_name = undefined
  ElMessage.success('已移除会话附件')
}

/** 文件选择完成后上传：招投标文件常规存储返回 path；对话附件只提取文本返回 extracted_text */
async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !pendingFile.value) return
  const lower = file.name.toLowerCase()
  if (!['.pdf', '.doc', '.docx', '.txt', '.md', '.csv'].some((ext) => lower.endsWith(ext))) {
    ElMessage.warning('仅支持 PDF/Word/文本文件（.pdf/.doc/.docx/.txt/.md/.csv）')
    return
  }
  const purpose = pendingFile.value.upload_purpose
  try {
    if (purpose === 0) {
      // 对话附件：绑定到当前会话（storage_scene=2 只提取内容不存文件，文本写入 sessions.attachment_text）
      const session = activeSession.value
      if (!session) {
        ElMessage.warning('请先选择或新建一个会话，再上传附件')
        pendingFile.value = null
        return
      }
      const res = await uploadFileApi(file, {
        upload_purpose: 0,
        storage_scene: 2,
        session_id: session.id,
      })
      if (!res.extracted_text) {
        ElMessage.warning('未能从该文件中提取到文本内容（扫描件暂不支持）')
        pendingFile.value = null
        return
      }
      session.attachment_name = res.filename
      inputDraft.value = '请阅读我上传的附件并回答问题'
      ElMessage.success('附件已绑定到本会话，发送消息将自动携带')
      return
    }
    // 招投标文件：常规存储，返回 minio 路径供 Agent 解析/审核
    const res = await uploadFileApi(file, {
      upload_purpose: purpose,
      storage_scene: 0,
      session_id: activeSession.value?.id,
    })
    if (!res.path) {
      ElMessage.error('上传失败，未获取到文件路径')
      pendingFile.value = null
      return
    }
    pendingFile.value = { upload_purpose: purpose, file_path: res.path }
    inputDraft.value =
      purpose === 1 ? '我上传了一份招标文件，帮我解析' : '我上传了一份投标文件，帮我审核'
    ElMessage.success('文件上传成功，可编辑消息后发送')
  } catch {
    pendingFile.value = null
    /* 错误提示由 request 拦截器统一处理 */
  }
}

// ── HITL 审核动作（BiddingReviewPanel emit 后在此执行）──

/** 确认解析结果：恢复图执行（rag_recall -> agent 最终回复） */
async function handleConfirmParsed(review: HitlPayload) {
  const session = toWorkSession()
  if (!session) return
  await resumeHitl(review, session)
  await nextTick()
  scrollToBottomNow()
}

/** 通过/驳回/修改后通过自检审核：resume 恢复图执行（驳回后图回到 generate 重新生成） */
async function handleSelfcheck(
  review: HitlPayload,
  action: 'approve' | 'reject' | 'modified',
  modifiedSections?: Record<string, string>,
) {
  const session = toWorkSession()
  if (!session) return
  await resumeHitl(review, session, {
    approved: action !== 'reject',
    modified_sections: modifiedSections,
  })
  await nextTick()
  scrollToBottomNow()
}

/** 审核任务提交完成后从队列移除 */
function handleRemoveReview(review: HitlPayload) {
  hitlQueue.value = hitlQueue.value.filter((h) => h.review_task_id !== review.review_task_id)
}

// ── 发送：走 SSE 流式接口，AI 回复逐字回填；携带文件附件上下文 ──
async function handleSend(text: string) {
  let session = activeSession.value
  if (!session) {
    const res = await createSessionApi({ role_type: roleType.value, intent_type: 0 })
    session = res.data.data
    activeSession.value = session
    messages.value = []
    hasMore.value = false
  }
  const fileContext = pendingFile.value ?? undefined
  pendingFile.value = null
  inputDraft.value = ''
  await sendMessage(
    text,
    { id: session.id, intent_type: session.intent_type ?? 0 },
    fileContext,
    (data) => {
      currentTopology.value = data
    },
  )
  await nextTick()
  scrollToBottomNow()
}

// 流式输出期间跟随滚动到底部（仅当末尾消息处于流式中，避免干扰上拉分页）
watch(
  () => {
    const last = messages.value[messages.value.length - 1]
    return last ? `${last.id}|${last.content}|${last.isStreaming}` : ''
  },
  () => {
    if (isSending.value || messages.value[messages.value.length - 1]?.isStreaming) {
      scrollToBottomNow()
    }
  },
)

onBeforeUnmount(reset)
</script>

<template>
  <div class="chat-view">
    <!-- 左侧会话列表 -->
    <ConversationList
      :role-type="roleType"
      :active-id="activeSession?.id ?? null"
      :intent-types="allowedIntentTypes"
      @select="handleSelect"
      @created="handleCreated"
    />

    <!-- 中间聊天区 -->
    <div class="chat-main">
      <!-- 会话标题栏：展示当前会话名与类型，可退出当前会话回到空态 -->
      <div v-if="activeSession" class="chat-titlebar">
        <span class="chat-titlebar-name" :title="activeSession.title">{{ activeSession.title }}</span>
        <el-tag size="small" effect="plain">
          {{ INTENT_TYPES.find((t) => t.value === activeSession?.intent_type)?.label || '对话' }}
        </el-tag>
        <el-button link type="primary" size="small" class="chat-titlebar-exit" @click="handleSelect(null)">
          退出会话
        </el-button>
      </div>

      <!-- 招投标流程步骤条（intent=1 会话） -->
      <div v-if="showBiddingCard" class="bidding-steps">
        <div v-for="(step, idx) in steps" :key="step.id" class="bs-item">
          <div v-if="idx > 0" class="bs-connector"></div>
          <div class="bs-circle" :class="step.status">
            {{ step.status === 'done' ? '✓' : step.id }}
          </div>
          <span class="bs-label" :class="step.status">{{ step.label }}</span>
        </div>
      </div>

      <!-- 任务卡片：招投标 / 测评核查 -->
      <div v-if="showBiddingCard || showAssessmentCard" class="task-area">
        <BiddingTaskCard v-if="showBiddingCard" :session-id="activeSession!.id" />
        <AssessmentTaskCard v-if="showAssessmentCard" :session-id="activeSession!.id" />
      </div>

      <!-- 网络拓扑图（Agent 生成拓扑后显示，历史会话进入时自动加载） -->
      <TopologyPanel v-if="currentTopology" :topology-data="currentTopology" />

      <div
        ref="messagesRef"
        class="chat-messages"
        @scroll="onMessagesScroll"
      >
        <div v-if="!activeSession" class="empty-state">
          <div class="empty-icon">💬</div>
          <div class="empty-text">选择或新建一个会话开始对话</div>
        </div>

        <template v-else>
          <div v-if="loading" class="load-tip">加载中…</div>
          <div v-else-if="!messages.length" class="empty-state">
            <div class="empty-text">暂无消息，开始你的第一句吧</div>
          </div>

          <MessageItem
            v-for="msg in renderMessages"
            :key="msg.id"
            :message="msg"
          />

          <div v-if="loadingOlder" class="load-tip">加载更早消息…</div>
        </template>
      </div>

      <!-- 输入区：招投标上传 / 对话附件上传 / 停止生成 / 输入 -->
      <div class="chat-input-area">
        <template v-if="showBiddingCard">
          <el-button size="small" class="upload-btn" @click="triggerUpload(1)">上传招标文件</el-button>
          <el-button size="small" class="upload-btn" @click="triggerUpload(5)">上传投标文件</el-button>
        </template>
        <template v-else>
          <div v-if="activeSession?.attachment_name" class="attachment-badge">
            <span class="attachment-name" :title="activeSession.attachment_name">📎 {{ activeSession.attachment_name }}</span>
            <el-button link type="danger" size="small" @click="handleClearAttachment">移除</el-button>
            <el-button link size="small" @click="triggerAttachment">更换</el-button>
          </div>
          <el-button v-else size="small" class="upload-btn" @click="triggerAttachment">上传附件</el-button>
        </template>
        <el-button
          v-if="isSending"
          class="abort-btn"
          type="warning"
          plain
          @click="abort"
        >
          停止生成
        </el-button>
        <input
          ref="fileInputRef"
          type="file"
          accept=".pdf,.doc,.docx,.txt,.md,.csv"
          class="hidden-file"
          @change="onFileChange"
        />
        <ChatInputBar v-model="inputDraft" @send="handleSend" />
      </div>
    </div>

    <!-- 右侧：招投标 HITL 审核面板（intent=1 会话） -->
    <BiddingReviewPanel
      v-if="showBiddingCard"
      :hitl-queue="hitlQueue"
      :is-sending="isSending"
      :session="toWorkSession()"
      @confirm-parsed="handleConfirmParsed"
      @selfcheck="handleSelfcheck"
      @remove-review="handleRemoveReview"
    />
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  height: 100%;
}

/* ── 聊天区 ── */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #fafbfc;
}
.chat-titlebar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 24px 0;
  background: #fafbfc;
}
.chat-titlebar-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 320px;
}
.chat-titlebar-exit {
  margin-left: auto;
  flex-shrink: 0;
}
.task-area {
  padding: 16px 24px 0;
  max-width: 860px;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-muted);
}
.empty-icon {
  font-size: 40px;
}
.empty-text {
  font-size: 14px;
}
.load-tip {
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
  padding: 8px 0;
}

/* ── 招投标流程步骤条（intent=1 会话）── */
.bidding-steps {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px 0;
  background: #fafbfc;
}
.bs-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.bs-connector {
  width: 24px;
  height: 2px;
  background: var(--border);
}
.bs-circle {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
  background: #f3f4f6;
  color: var(--text-muted);
}
.bs-circle.done {
  background: var(--success);
  color: #fff;
}
.bs-circle.active {
  background: var(--primary);
  color: #fff;
}
.bs-label {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}
.bs-label.done {
  color: var(--text);
}
.bs-label.active {
  color: var(--primary);
  font-weight: 500;
}

/* ── 输入区：上传按钮 + 输入框 ── */
.chat-input-area {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 8px;
}
.chat-input-area .upload-btn {
  flex-shrink: 0;
  margin-left: 4px;
}
.chat-input-area .attachment-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding: 2px 6px;
  background: #f3f6ff;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 12px;
  color: var(--primary);
  max-width: 220px;
}
.chat-input-area .attachment-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-input-area .abort-btn {
  flex-shrink: 0;
}
.chat-input-area .hidden-file {
  display: none;
}
.chat-input-area :deep(.chat-input-bar) {
  flex: 1;
  min-width: 0;
  padding-left: 0;
  border-top: none;
}
</style>
