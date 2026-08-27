<script setup lang="ts">
/**
 * 技术 - 测评核查工作台（intent_type=2）。
 * 三层结构：左侧控制点清单 / 中间流式对话区 / 右侧低置信度复核面板（HITL）+ 截图上传。
 * 会话由页面层自动获取或创建；控制点清单由 task_created 事件（或历史消息 task_id）写入。
 */
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import type { ChatMessage, Conversation } from '@/types/chat'
import { ASSESSMENT_STAGES } from '@/types/chat'
import type { TopologyData } from '@/types/topology'
import MessageItem from '@/components/chat/MessageItem.vue'
import ChatInputBar from '@/components/chat/ChatInputBar.vue'
import TopologyPanel from '@/components/topology/TopologyPanel.vue'
import {
  createSessionApi,
  getAssessmentRecordsApi,
  getMessagesApi,
  getReviewDetailApi,
  getReviewsApi,
  getSessionsApi,
  getSessionTopologyApi,
  submitHumanRecordApi,
  submitReviewApi,
  uploadFileApi,
  uploadScreenshotApi,
  type ReviewDetail,
} from '@/utils/chat-api'
import {
  useSessionStreamSender,
  type StreamMessage,
  type WorkSession,
} from '@/composables/useSessionStreamSender'
import type { ToolCallPayload } from '@/utils/streamChat'
import type { AssessmentRecord } from '@/types/chat'

/** VLM 截图分析结果（assessment_records.vlm_analysis） */
interface VlmAnalysis {
  recognized_text?: string
  detected_items?: string[]
  raw_response?: string
  error?: string
  detail?: string
}

/** 企业本地库特殊情况说明（kb_references 项） */
interface KbReference {
  doc_title?: string
  matched_text?: string
  chunk?: string
  similarity?: number
}

/** AI 与人工记录比对结果（comparison_result） */
interface ComparisonResult {
  consistent?: boolean | null
  ai_result?: string
  human_result?: string
  diff_detail?: string | unknown[]
  confidence?: number
  kb_references?: KbReference[]
}

/** 低置信度复核数据（hitl review_data 子集） */
interface AssessmentReviewData {
  comparison_result?: {
    ai_result?: string
    human_result?: string
    consistent?: boolean | null
    diff_detail?: unknown[]
  }
  confidence?: number
  kb_references?: Array<{
    doc_title?: string
    chunk?: string
    similarity?: number
    kb_type?: number
  }>
}

const { messages, isSending, currentTask, sendMessage, abort, reset } =
  useSessionStreamSender()

const session = ref<WorkSession | null>(null)
const initLoading = ref(true)
const messagesRef = ref<HTMLElement | null>(null)

/** 当前会话标题（对话助手确定测评系统后，即核查进度清单名称） */
const sessionTitle = ref('')

/** 网络拓扑图数据（Agent 调用 generate_topology 后经 topology SSE 事件写入） */
const currentTopology = ref<TopologyData | null>(null)

/** 技术侧测评项目（intent_type=2 会话）列表：每个会话对应一个被测系统的核查清单 */
const projects = ref<Conversation[]>([])

/** 当前选中项目 id（下拉选择器 v-model） */
const activeSid = computed<number | null>({
  get: () => session.value?.id ?? null,
  set: (v) => {
    if (v && v !== session.value?.id) handleProjectChange(v)
  },
})

/** 控制点清单：启动 / task_created 后从后端同步（含测评命令、截图、比对等完整字段） */
const records = ref<AssessmentRecord[]>([])
const selectedId = ref<number | null>(null)
const expandedId = ref<number | null>(null)
const dialogVisible = ref(false)
const activeRecord = ref<AssessmentRecord | null>(null)
const humanRecordDraft = ref('')
const submittingRecord = ref(false)

const checkpoints = computed(() => records.value)

/** 已通过控制点数（status=3 自动通过 / 5 已确认） */
const doneCount = computed(() => records.value.filter((r) => r.status === 3 || r.status === 5).length)
/** 待人工复核控制点数（status=4） */
const reviewCount = computed(() => records.value.filter((r) => r.status === 4).length)

/** 当前选中控制点（截图上传目标） */
const selectedRecord = computed(() => records.value.find((r) => r.id === selectedId.value) ?? null)

/** 待低置信度复核的任务队列（task_type=1 低置信度复核，来自 GET /review 待审核列表） */
const reviewQueue = ref<ReviewDetail[]>([])

/** 从后端拉取低置信度复核任务（含 review_data 详情），只保留当前项目的 */
async function refreshReviews() {
  try {
    const res = await getReviewsApi(0)
    const tasks = res.data.data.groups?.[1] ?? []
    const details = await Promise.all(
      tasks.map((t) => getReviewDetailApi(t.review_task_id).then((r) => r.data.data)),
    )
    const recordIds = new Set(records.value.map((r) => r.id))
    reviewQueue.value = details.filter((d) => {
      const recordId = (d.review_data as { record_id?: number } | undefined)?.record_id
      return recordId !== undefined && recordIds.has(recordId)
    })
  } catch {
    /* 错误提示由 request 拦截器统一处理 */
  }
}

const dialogTitle = computed(() =>
  activeRecord.value
    ? `${activeRecord.value.checklist_code} ${activeRecord.value.checklist_name}`
    : '控制点详情',
)

function stageLabel(status: number): string {
  return ASSESSMENT_STAGES.find((s) => s.status === status)?.label ?? '未知'
}

function stageTagType(status: number): 'info' | 'success' | 'warning' | 'danger' | 'primary' {
  if (status === 2) return 'primary'
  if (status === 3 || status === 5) return 'success'
  if (status === 4) return 'warning'
  if (status === 6) return 'danger'
  return 'info'
}

function vlmOf(rec: AssessmentRecord | null): VlmAnalysis | null {
  if (!rec?.vlm_analysis || typeof rec.vlm_analysis !== 'object') return null
  return rec.vlm_analysis as unknown as VlmAnalysis
}

function comparisonOf(rec: AssessmentRecord | null): ComparisonResult | null {
  if (!rec?.comparison_result || typeof rec.comparison_result !== 'object') return null
  return rec.comparison_result as unknown as ComparisonResult
}

function kbRefs(rec: AssessmentRecord | null): KbReference[] {
  if (!rec?.kb_references || !Array.isArray(rec.kb_references)) return []
  return rec.kb_references as unknown as KbReference[]
}

function fmtDiff(diff: string | unknown[] | undefined): string {
  if (typeof diff === 'string') return diff
  if (Array.isArray(diff)) {
    return diff.map((d) => (typeof d === 'string' ? d : JSON.stringify(d))).join('；')
  }
  return ''
}

/** 从后端同步控制点清单（启动 / task_created / 上传 / 提交后调用） */
async function refreshRecords() {
  if (!session.value) return
  try {
    const res = await getAssessmentRecordsApi(session.value.id)
    records.value = res.data.data.items
    if (records.value.length && selectedId.value === null) {
      selectedId.value = records.value[0].id
    }
    // 刷新会话标题（对话助手生成清单后标题同步为"被测系统名 等保X级测评"，即清单名）
    try {
      const sres = await getSessionsApi({ page: 1, page_size: 50, role_type: 1 })
      const found = sres.data.data.items.find((s) => s.id === session.value!.id)
      if (found?.title) sessionTitle.value = found.title
    } catch {
      /* 标题刷新失败不影响清单展示 */
    }
    syncActiveRecord()
  } catch {
    /* 错误提示由 request 拦截器统一处理 */
  }
}

/** 重新拉取会话消息（核查操作写回的【测评核查】汇报消息会出现在对话里） */
async function refreshMessages() {
  if (!session.value) return
  try {
    const res = await getMessagesApi(session.value.id, { before_id: null, limit: 50 })
    messages.value = res.data.data.items.map(toStreamMessage)
    const last = res.data.data.items[res.data.data.items.length - 1]
    if (last) currentTask.value = { intentType: 2, taskId: last.task_id ?? null }
  } catch {
    /* 错误提示由 request 拦截器统一处理 */
  }
}

function syncActiveRecord() {
  if (activeRecord.value) {
    const fresh = records.value.find((r) => r.id === activeRecord.value!.id)
    if (fresh) activeRecord.value = fresh
  }
}

function reviewData(review: ReviewDetail): AssessmentReviewData {
  return (review.review_data ?? {}) as AssessmentReviewData
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

/** 拉取技术侧测评项目列表（intent_type=2 会话，后端按更新时间倒序） */
async function loadProjects(): Promise<Conversation[]> {
  const res = await getSessionsApi({ page: 1, page_size: 100, role_type: 1 })
  return res.data.data.items.filter((s) => s.intent_type === 2)
}

/** 加载指定项目的消息 / 清单 / 复核任务 / 标题 */
async function loadSession(sid: number) {
  initLoading.value = true
  try {
    const conv = projects.value.find((p) => p.id === sid)
    session.value = { id: sid, intent_type: 2 }
    sessionTitle.value = conv?.title || '测评控制点'
    const res = await getMessagesApi(sid, { before_id: null, limit: 50 })
    messages.value = res.data.data.items.map(toStreamMessage)
    const last = res.data.data.items[res.data.data.items.length - 1]
    currentTask.value = { intentType: 2, taskId: last?.task_id ?? null }
    await loadSessionTopology(sid)
    await refreshRecords()
    await refreshReviews()
  } finally {
    initLoading.value = false
  }
  scrollToBottom()
}

/** 加载会话历史网络拓扑（无则清空；仅测评项目会话存在拓扑记录） */
async function loadSessionTopology(sid: number) {
  try {
    const res = await getSessionTopologyApi(sid)
    currentTopology.value = res.data.data ?? null
  } catch {
    currentTopology.value = null
  }
}

/** 进入页面：拉取测评项目列表，无则自动新建，默认选中最近的项目 */
async function ensureSession() {
  initLoading.value = true
  try {
    let list = await loadProjects()
    if (!list.length) {
      const created = await createSessionApi({ role_type: 1, intent_type: 2 })
      list = [created.data.data]
    }
    projects.value = list
    await loadSession(list[0].id)
  } finally {
    initLoading.value = false
  }
}

/** 切换测评项目：清空当前页面状态后加载目标项目数据 */
async function handleProjectChange(sid: number) {
  if (sid === session.value?.id) return
  reset() // 中断流式请求并清空消息 / 任务状态
  records.value = []
  selectedId.value = null
  expandedId.value = null
  activeRecord.value = null
  humanRecordDraft.value = ''
  reviewQueue.value = []
  await loadSession(sid)
}

/** 新建测评项目并切换过去（对话里确定系统名后清单标题会自动同步） */
async function handleCreateProject() {
  try {
    const created = await createSessionApi({ role_type: 1, intent_type: 2, title: '新测评项目' })
    projects.value = [created.data.data, ...projects.value]
    await handleProjectChange(created.data.data.id)
  } catch {
    /* 错误提示由 request 拦截器统一处理 */
  }
}

function handleSend(text: string) {
  if (!session.value) return
  sendMessage(text, session.value, undefined, (data) => {
    currentTopology.value = data
  }).then(scrollToBottom)
}

/** 上传资产核查表：提取内容后发送给 Agent，由 generate_topology 生成网络拓扑图 */
async function handleUploadAsset(options: { file: File }) {
  if (!session.value) return
  const file = options.file
  const uploading = ElMessage({ message: '资产核查表解析中…', type: 'info', duration: 0 })
  try {
    const res = await uploadFileApi(file, {
      upload_purpose: 4,
      session_id: session.value.id,
    })
    const extracted = res.extracted_text || ''
    if (!extracted) {
      ElMessage.warning('未从资产核查表中提取到内容')
      return
    }
    const text = `请根据我上传的资产核查表生成网络拓扑图。\n\n【资产核查表内容】\n${extracted}`
    sendMessage(text, session.value, { upload_purpose: 4 }, (data) => {
      currentTopology.value = data
    }).then(scrollToBottom)
    ElMessage.success('资产核查表已上传，正在生成网络拓扑图…')
  } catch {
    /* 错误提示由 request 拦截器统一处理 */
  } finally {
    uploading.close()
  }
}

/** 提交低置信度复核：通过 / 驳回（后端回写 assessment_records.status=5/4） */
async function handleReview(review: ReviewDetail, action: 'approve' | 'reject') {
  try {
    await submitReviewApi(review.review_task_id, { action })
    ElMessage.success(action === 'approve' ? '已确认通过' : '已驳回待整改')
    await refreshReviews()
    await refreshRecords()
    await refreshMessages()
  } catch {
    /* 错误提示由 request 拦截器统一处理 */
  }
}

/** 选中控制点：作为截图上传目标 */
function selectRecord(rec: AssessmentRecord) {
  selectedId.value = rec.id
}

function toggleCommand(recId: number) {
  expandedId.value = expandedId.value === recId ? null : recId
}

/** 打开控制点详情弹窗 */
function openDetail(rec: AssessmentRecord) {
  activeRecord.value = rec
  humanRecordDraft.value = rec.human_record ?? ''
  dialogVisible.value = true
}

async function handleCopyCommand(command: string) {
  if (!command) return
  try {
    await navigator.clipboard.writeText(command)
    ElMessage.success('测评命令已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

/** 截图上传（record_id 级）：POST /assessment/{id}/upload_screenshot，后端自动 VLM 分析 */
async function handleUpload(options: { file: File; onSuccess: (result: unknown) => void; onError: (err: Error) => void }) {
  if (!selectedRecord.value) {
    ElMessage.warning('请先在左侧选择控制点')
    options.onError(new Error('未选择控制点'))
    return
  }
  try {
    const res = await uploadScreenshotApi(selectedRecord.value.id, options.file)
    ElMessage.success('截图已上传并完成 VLM 分析')
    await refreshRecords()
    await refreshReviews()
    await refreshMessages()
    options.onSuccess(res)
  } catch (err) {
    options.onError(err as Error)
  }
}

/** 提交人工记录：PUT /assessment/{id}/human_record，已有 VLM 结果则自动比对 */
async function handleSubmitHumanRecord() {
  if (!activeRecord.value) return
  const text = humanRecordDraft.value.trim()
  if (!text) {
    ElMessage.warning('请填写人工记录')
    return
  }
  submittingRecord.value = true
  try {
    const res = await submitHumanRecordApi(activeRecord.value.id, text)
    ElMessage.success(res.data.data.comparison_done ? '人工记录已提交并完成比对' : '人工记录已提交')
    await refreshRecords()
    await refreshReviews()
    await refreshMessages()
  } catch {
    /* 错误提示由 request 拦截器统一处理 */
  } finally {
    submittingRecord.value = false
  }
}

function scrollToBottom() {
  nextTick(() => {
    const el = messagesRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

// 清单生成（task_created 事件）后从后端同步完整控制点数据
watch(currentTask, () => {
  if (currentTask.value?.intentType === 2) refreshRecords()
})

watch(
  () => messages.value.map((m) => `${m.content}|${m.isStreaming}`),
  () => scrollToBottom(),
)

onMounted(ensureSession)
onBeforeUnmount(reset)
</script>

<template>
  <div class="workbench">
    <!-- 左侧：控制点清单 -->
    <aside class="side-panel checkpoints-panel">
      <div class="project-selector">
        <el-select v-model="activeSid" placeholder="选择测评项目" size="small" style="flex: 1">
          <el-option v-for="p in projects" :key="p.id" :label="p.title" :value="p.id" />
        </el-select>
        <el-button size="small" @click="handleCreateProject">＋ 新建</el-button>
      </div>
      <div class="panel-title">
        {{ sessionTitle || '测评控制点' }}
        <span v-if="checkpoints.length" class="checklist-summary">
          {{ doneCount }}/{{ checkpoints.length }} 已核查
        </span>
      </div>
      <div v-if="reviewCount" class="checklist-review-note">{{ reviewCount }} 项待人工复核</div>
      <div v-if="!checkpoints.length" class="empty-state">
        <div class="empty-text">发送消息开始测评，将自动生成控制点清单</div>
      </div>
      <div v-else class="checkpoint-list">
        <div
          v-for="cp in checkpoints"
          :key="cp.id"
          class="checkpoint-item"
          :class="{ active: cp.id === selectedId }"
          @click="selectRecord(cp)"
        >
          <div class="checkpoint-header">
            <el-tag :type="stageTagType(cp.status)" size="small" effect="plain">
              {{ stageLabel(cp.status) }}
            </el-tag>
            <span class="checkpoint-code">{{ cp.checklist_code }}</span>
          </div>
          <div class="checkpoint-name">{{ cp.checklist_name }}</div>
          <el-progress
            v-if="cp.confidence > 0"
            class="confidence-bar"
            :percentage="Math.round(cp.confidence * 100)"
            :stroke-width="6"
            :show-text="false"
            :status="cp.status === 4 ? 'warning' : undefined"
          />
          <div v-if="cp.confidence > 0" class="confidence-label">
            置信度 {{ Math.round(cp.confidence * 100) }}%
          </div>
          <div v-else class="confidence-placeholder">未测评</div>
          <div class="checkpoint-actions">
            <el-button link type="primary" size="small" @click.stop="toggleCommand(cp.id)">
              {{ expandedId === cp.id ? '收起命令' : '测评命令' }}
            </el-button>
            <el-button link type="primary" size="small" @click.stop="openDetail(cp)">详情</el-button>
          </div>
          <div v-if="expandedId === cp.id && cp.assessment_command" class="command-box">
            <pre class="command-text">{{ cp.assessment_command }}</pre>
            <el-button link type="primary" size="small" @click.stop="handleCopyCommand(cp.assessment_command!)">
              复制
            </el-button>
          </div>
        </div>
      </div>
    </aside>

    <!-- 中间：流式对话区 + 网络拓扑图 -->
    <section class="chat-panel">
      <!-- 网络拓扑图（Agent 调用 generate_topology 生成拓扑数据后显示） -->
      <TopologyPanel v-if="currentTopology" :topology-data="currentTopology" />
      <div class="panel-header">
        <span class="panel-title">{{ sessionTitle || '技术对话' }}</span>
        <div class="header-actions">
          <el-tag type="success" effect="plain" size="small">测评核查</el-tag>
          <el-upload
            :show-file-list="false"
            accept=".xlsx,.xls,.doc,.docx,.txt,.csv,.pdf"
            :http-request="handleUploadAsset"
          >
            <el-button size="small" type="primary" plain>上传资产核查表</el-button>
          </el-upload>
        </div>
      </div>
      <div ref="messagesRef" class="chat-messages">
        <div v-if="initLoading" class="empty-state">加载会话中…</div>
        <div v-else-if="!renderMessages.length" class="empty-state">
          <div class="empty-text">输入核查指令，开始测评核查</div>
        </div>
        <template v-else>
          <MessageItem v-for="msg in renderMessages" :key="msg.id" :message="msg" />
        </template>
      </div>
      <div class="chat-input-area">
        <el-button
          v-if="isSending"
          class="abort-btn"
          type="warning"
          plain
          @click="abort"
        >
          停止生成
        </el-button>
        <ChatInputBar @send="handleSend" />
      </div>
    </section>

    <!-- 右侧：复核面板 + 截图上传 -->
    <aside class="side-panel review-panel">
      <div class="panel-title">低置信度复核</div>
      <div v-if="!reviewQueue.length" class="empty-state">
        <div class="empty-text">暂无待复核项</div>
      </div>
      <template v-else>
        <div v-for="review in reviewQueue" :key="review.review_task_id" class="review-card">
          <el-alert title="AI 结果与人工记录不一致" type="warning" :closable="false" show-icon />
          <div class="review-block">
            <div class="review-label">AI 识别结果</div>
            <div class="review-content">
              {{ reviewData(review).comparison_result?.ai_result || '（无）' }}
            </div>
          </div>
          <div class="review-block">
            <div class="review-label">人工记录</div>
            <div class="review-content">
              {{ reviewData(review).comparison_result?.human_result || '（无）' }}
            </div>
          </div>
          <div class="review-block">
            <div class="review-label">一致性</div>
            <div class="review-content">
              <el-tag
                :type="reviewData(review).comparison_result?.consistent === false ? 'danger' : 'success'"
                size="small"
              >
                {{ reviewData(review).comparison_result?.consistent === false ? '不一致' : '一致' }}
              </el-tag>
            </div>
          </div>
          <div class="review-block">
            <div class="review-label">置信度</div>
            <el-progress
              class="confidence-bar"
              :percentage="Math.round((reviewData(review).confidence ?? 0) * 100)"
              :stroke-width="8"
            />
          </div>
          <div v-if="reviewData(review).kb_references?.length" class="review-block">
            <div class="review-label">KB 参考说明</div>
            <div
              v-for="(ref, idx) in reviewData(review).kb_references"
              :key="idx"
              class="kb-ref"
            >
              <div class="kb-ref-title">{{ ref.doc_title || '参考文档' }}</div>
              <div class="kb-ref-chunk">{{ ref.chunk }}</div>
            </div>
          </div>
          <div class="review-actions">
            <el-button type="success" size="small" @click="handleReview(review, 'approve')">通过</el-button>
            <el-button type="danger" size="small" @click="handleReview(review, 'reject')">驳回</el-button>
          </div>
        </div>
      </template>

      <div class="panel-title upload-title">截图上传</div>
      <div v-if="selectedRecord" class="upload-target">
        <div class="upload-target-line">
          当前控制点：<b>{{ selectedRecord.checklist_code }} {{ selectedRecord.checklist_name }}</b>
        </div>
        <el-tag :type="stageTagType(selectedRecord.status)" size="small" effect="plain">
          {{ stageLabel(selectedRecord.status) }}
        </el-tag>
      </div>
      <div v-else class="upload-target muted">请先在左侧选择控制点</div>
      <el-upload
        drag
        :show-file-list="false"
        accept="image/*"
        :http-request="handleUpload"
        :disabled="!selectedRecord"
      >
        <div class="upload-hint">拖拽或点击上传测评截图</div>
        <div class="upload-sub">
          上传后自动 VLM 分析{{ selectedRecord?.human_record ? '并比对人工记录' : '' }}
        </div>
      </el-upload>

      <!-- 控制点详情弹窗 -->
      <el-dialog v-model="dialogVisible" :title="dialogTitle" width="660px" top="6vh">
        <template v-if="activeRecord">
          <div class="detail-block">
            <div class="detail-label">
              测评命令
              <el-button link type="primary" size="small" @click="handleCopyCommand(activeRecord.assessment_command || '')">
                复制
              </el-button>
            </div>
            <pre class="detail-command">{{ activeRecord.assessment_command || '（无）' }}</pre>
          </div>

          <div class="detail-block">
            <div class="detail-label">VLM 截图分析</div>
            <template v-if="vlmOf(activeRecord)">
              <div v-if="vlmOf(activeRecord)?.error" class="detail-content danger">
                {{ vlmOf(activeRecord)?.error }}
                <span v-if="vlmOf(activeRecord)?.detail">（{{ vlmOf(activeRecord)?.detail }}）</span>
              </div>
              <template v-else>
                <div class="detail-sub">识别文本</div>
                <div class="detail-content">{{ vlmOf(activeRecord)?.recognized_text || '（无）' }}</div>
                <div class="detail-sub">检测项</div>
                <div class="detect-items">
                  <el-tag
                    v-for="(item, idx) in (vlmOf(activeRecord)?.detected_items ?? [])"
                    :key="idx"
                    size="small"
                    type="success"
                    effect="plain"
                  >
                    {{ item }}
                  </el-tag>
                </div>
              </template>
            </template>
            <div v-else class="detail-content muted">尚未上传截图，请在右侧上传区为该控制点上传截图</div>
          </div>

          <div class="detail-block">
            <div class="detail-label">人工记录</div>
            <el-input
              v-model="humanRecordDraft"
              type="textarea"
              :rows="3"
              placeholder="组员填写该控制点的实际测评结果（将自动与 VLM 识别结果比对）"
            />
            <div class="submit-row">
              <el-button
                type="primary"
                size="small"
                :loading="submittingRecord"
                @click="handleSubmitHumanRecord"
              >
                提交人工记录{{ activeRecord.vlm_analysis ? '（自动比对）' : '' }}
              </el-button>
            </div>
          </div>

          <div class="detail-block">
            <div class="detail-label">比对结果</div>
            <template v-if="comparisonOf(activeRecord)">
              <div class="cmp-row">
                <span class="cmp-name">AI 识别</span>
                <span class="cmp-val">{{ comparisonOf(activeRecord)?.ai_result || '（无）' }}</span>
              </div>
              <div class="cmp-row">
                <span class="cmp-name">人工记录</span>
                <span class="cmp-val">{{ comparisonOf(activeRecord)?.human_result || '（无）' }}</span>
              </div>
              <div class="cmp-row">
                <span class="cmp-name">一致性</span>
                <el-tag
                  :type="comparisonOf(activeRecord)?.consistent === false ? 'danger' : 'success'"
                  size="small"
                >
                  {{ comparisonOf(activeRecord)?.consistent === false ? '不一致' : '一致' }}
                </el-tag>
              </div>
              <div v-if="fmtDiff(comparisonOf(activeRecord)?.diff_detail)" class="cmp-row">
                <span class="cmp-name">差异详情</span>
                <span class="cmp-val">{{ fmtDiff(comparisonOf(activeRecord)?.diff_detail) }}</span>
              </div>
              <div class="cmp-row">
                <span class="cmp-name">置信度</span>
                <el-progress
                  class="confidence-bar"
                  :percentage="Math.round(activeRecord.confidence * 100)"
                  :stroke-width="8"
                  :status="activeRecord.confidence < 0.8 ? 'warning' : 'success'"
                />
              </div>
            </template>
            <div v-else class="detail-content muted">上传截图并提交人工记录后自动比对</div>
          </div>

          <div v-if="kbRefs(activeRecord).length" class="detail-block">
            <div class="detail-label">企业本地库特殊说明</div>
            <div v-for="(ref, idx) in kbRefs(activeRecord)" :key="idx" class="kb-ref">
              <div class="kb-ref-title">{{ ref.doc_title || '参考文档' }}</div>
              <div class="kb-ref-chunk">{{ ref.matched_text || ref.chunk }}</div>
              <div v-if="ref.similarity !== undefined" class="kb-ref-score">
                相似度 {{ Math.round(ref.similarity * 100) }}%
              </div>
            </div>
          </div>
        </template>
      </el-dialog>
    </aside>
  </div>
</template>

<style scoped>
.workbench {
  display: flex;
  height: 100%;
  gap: 16px;
  padding: 16px;
  background: #f5f6f8;
}
.side-panel {
  width: 260px;
  flex-shrink: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  overflow-y: auto;
}
.project-selector {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 16px;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}
.checklist-summary {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-muted);
}
.checklist-review-note {
  font-size: 12px;
  color: #e6a23c;
  margin: -10px 0 12px;
}
.upload-title {
  margin-top: 24px;
}
/* 控制点清单 */
.checkpoint-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.checkpoint-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  background: #fafbfc;
}
.checkpoint-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
.checkpoint-code {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.checkpoint-name {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.confidence-bar {
  width: 100%;
}
.confidence-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}
/* 对话区 */
.chat-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
}
.panel-header .panel-title {
  margin-bottom: 0;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  background: #fafbfc;
}
.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 14px;
}
.empty-text {
  color: var(--text-muted);
}
.chat-input-area {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--surface);
  border-top: 1px solid var(--border);
}
.abort-btn {
  margin-left: 16px;
  flex-shrink: 0;
}
.chat-input-area :deep(.chat-input-bar) {
  flex: 1;
  padding-left: 8px;
}
/* 复核面板 */
.review-panel {
  width: 300px;
}
.review-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}
.review-block {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  background: #fafbfc;
}
.review-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.review-content {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}
.kb-ref {
  border-top: 1px dashed var(--border);
  padding-top: 6px;
  margin-top: 6px;
}
.kb-ref:first-child {
  border-top: none;
  padding-top: 0;
  margin-top: 0;
}
.kb-ref-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--primary);
}
.kb-ref-chunk {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
  margin-top: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.review-actions {
  display: flex;
  gap: 8px;
}
/* 上传 */
.upload-hint {
  font-size: 13px;
  color: var(--text-secondary);
}
.upload-sub {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}
/* 控制点：选中态 / 命令 / 占位 */
.checkpoint-item {
  cursor: pointer;
  transition: border-color 0.2s;
}
.checkpoint-item.active {
  border-color: var(--primary);
  background: #f0f7ff;
}
.checkpoint-actions {
  display: flex;
  align-items: center;
  margin-top: 2px;
}
.command-box {
  margin-top: 8px;
  border: 1px dashed var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  background: #fff;
}
.command-text {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-secondary);
}
.confidence-placeholder {
  font-size: 12px;
  color: var(--text-muted);
  margin: 4px 0;
}
/* 上传目标 */
.upload-target {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.upload-target-line b {
  color: var(--text);
}
.muted {
  color: var(--text-muted);
}
/* 详情弹窗 */
.detail-block {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
  background: #fafbfc;
}
.detail-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.detail-sub {
  font-size: 12px;
  color: var(--text-muted);
  margin: 8px 0 4px;
}
.detail-content {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}
.detail-content.danger {
  color: #f56c6c;
}
.detail-command {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  color: var(--text-secondary);
}
.detect-items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.submit-row {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}
.cmp-row {
  display: flex;
  gap: 10px;
  margin-bottom: 8px;
  align-items: flex-start;
}
.cmp-name {
  flex-shrink: 0;
  width: 64px;
  font-size: 12px;
  color: var(--text-muted);
  padding-top: 2px;
}
.cmp-val {
  flex: 1;
  font-size: 13px;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}
.kb-ref-score {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}
</style>
