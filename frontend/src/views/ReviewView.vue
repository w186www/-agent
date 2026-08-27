<script setup lang="ts">
/**
 * 审核工作台（ReviewWorkbench）。
 * 左侧：待审核任务列表（GET /review?status=0），按 task_type 分组展示摘要；
 * 右侧：审核详情面板（GET /review/{id}），按 task_type / review_data 形状渲染对应内容，
 * 提交审核走统一 POST /review/{id}，提交后刷新待审列表。
 */
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { Conversation } from '@/types/chat'
import type { ReviewItem } from '@/types/review'
import ReviewQueuePanel from '@/components/review/ReviewQueuePanel.vue'
import {
  getReviewsApi,
  getReviewDetailApi,
  getSessionsApi,
  submitReviewApi,
  type ReviewDetail,
  type ReviewSummary,
} from '@/utils/chat-api'

/** 待审任务摘要列表（后端按 task_type 分组，前端展平展示） */
const reviews = ref<ReviewSummary[]>([])
const activeId = ref<number | null>(null)
const detail = ref<ReviewDetail | null>(null)
const detailLoading = ref(false)
const submitting = ref(false)

/** 技术侧测评项目（intent_type=2 会话）：人工在此选择按项目审核低置信度项 */
const projects = ref<Conversation[]>([])
/** 当前筛选项目 id（null=全部项目） */
const activeSid = ref<number | null>(null)

const reviewItems = computed<ReviewItem[]>(() =>
  reviews.value.map((r) => ({
    id: r.review_task_id,
    category: r.category,
    title: r.title,
    confidence: r.confidence,
    time: formatTime(r.created_at),
    active: r.review_task_id === activeId.value,
  })),
)

function formatTime(ts: number): string {
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}月${d.getDate()}日 ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** task_type 映射标题：0=审核（报价/自检/投标文件），1=低置信度复核，2=解析结果确认，3=自检审核 */
const TASK_TITLES = ['审核任务', '低置信度复核', '解析结果确认', '自检审核'] as const

function taskTitle(taskType: number): string {
  return TASK_TITLES[taskType] ?? '审核任务'
}

/** 拉取技术侧测评项目列表（intent_type=2 会话，供筛选） */
async function loadProjects() {
  try {
    const res = await getSessionsApi({ page: 1, page_size: 100, role_type: 1 })
    projects.value = res.data.data.items.filter((s) => s.intent_type === 2)
  } catch {
    /* 错误提示由 request 拦截器统一处理 */
  }
}

async function loadList() {
  const res = await getReviewsApi(0, activeSid.value ?? undefined)
  reviews.value = Object.values(res.data.data.groups).flat() ?? []
  // 自动选中第一条待审任务
  if (reviews.value.length && activeId.value === null) {
    await selectReview(reviews.value[0].review_task_id)
  }
}

/** 切换测评项目筛选：重置选中后重新加载待审列表 */
async function handleProjectFilter() {
  activeId.value = null
  detail.value = null
  await loadList()
}

async function selectReview(id: number) {
  activeId.value = id
  detailLoading.value = true
  detail.value = null
  try {
    const res = await getReviewDetailApi(id)
    detail.value = res.data.data
  } finally {
    detailLoading.value = false
  }
}

async function handleSubmit(action: 'approve' | 'reject' | 'modified', comment?: string) {
  if (activeId.value === null) return
  submitting.value = true
  try {
    await submitReviewApi(activeId.value, { action, comment })
    ElMessage.success(action === 'approve' ? '审核通过' : action === 'reject' ? '已驳回' : '已修改后通过')
    activeId.value = null
    detail.value = null
    await loadList()
  } finally {
    submitting.value = false
  }
}

/** review_data 中投标文件审核项结构（与后端 review_bidding 结果对齐） */
interface BiddingItem {
  item?: string
  type?: string
  status?: string
  detail?: string
  confidence?: number
  need_human?: boolean
}

function biddingItems(): BiddingItem[] {
  const data = detail.value?.review_data ?? {}
  return Array.isArray(data.items) ? (data.items as BiddingItem[]) : []
}

function statusTagType(status?: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'pass') return 'success'
  if (status === 'danger') return 'danger'
  if (status === 'warning') return 'warning'
  return 'info'
}

function statusText(status?: string): string {
  if (status === 'pass') return '通过'
  if (status === 'danger') return '危险'
  if (status === 'warning') return '警告'
  return '未知'
}

onMounted(() => {
  loadProjects()
  loadList()
})
</script>

<template>
  <div class="review-page">
    <!-- 测评项目筛选：低置信度测评项由人工在此判断通过/驳回 -->
    <div class="filter-bar">
      <span class="filter-label">测评项目</span>
      <el-select
        v-model="activeSid"
        placeholder="全部项目"
        size="small"
        style="width: 300px"
        @change="handleProjectFilter"
      >
        <el-option :value="null" label="全部项目" />
        <el-option v-for="p in projects" :key="p.id" :label="p.title" :value="p.id" />
      </el-select>
    </div>
    <div class="review-view">
    <!-- 左侧待审队列 -->
    <ReviewQueuePanel :items="reviewItems" @select="selectReview" />

    <!-- 右侧详情面板 -->
    <div class="review-detail">
      <div v-if="detailLoading" class="empty-state">加载审核详情…</div>
      <div v-else-if="!detail" class="empty-state">
        <div class="empty-text">暂无待审核任务，点击左侧队列查看详情</div>
      </div>

      <template v-else>
        <div class="detail-header">
          <div>
            <h2 class="detail-title">{{ detail.review_task_id ? taskTitle(detail.task_type) : '' }}</h2>
            <div class="detail-sub">
              <el-tag size="small" effect="plain">{{ detail.review_data.bidding_review ? '投标文件审核' : '审核任务' }}</el-tag>
              <span class="detail-time">创建于 {{ formatTime(detail.created_at) }}</span>
            </div>
          </div>
          <div class="detail-actions">
            <el-button
              :loading="submitting"
              @click="handleSubmit('reject', '审核驳回')"
            >驳回</el-button>
            <el-button
              type="primary"
              :loading="submitting"
              @click="handleSubmit('approve', '审核通过')"
            >通过并继续</el-button>
          </div>
        </div>

        <!-- 投标文件审核（task_type=0 + review_data.bidding_review） -->
        <template v-if="detail.review_data.bidding_review">
          <el-alert
            :title="String(detail.review_data.summary ?? '投标文件审核结果')"
            type="warning"
            :closable="false"
            show-icon
          />
          <div class="detail-block">
            <div v-if="!biddingItems().length" class="muted">（无检查项）</div>
            <div
              v-for="(item, i) in biddingItems()"
              :key="i"
              class="bid-item"
              :class="{ 'bid-item-human': item.need_human }"
            >
              <div class="bid-item-top">
                <el-tag size="small" :type="statusTagType(item.status)" effect="plain">
                  {{ statusText(item.status) }}
                </el-tag>
                <span class="muted">{{ item.type || '检查项' }}</span>
                <el-tag v-if="item.need_human" size="small" type="danger" effect="plain">需人工确认</el-tag>
              </div>
              <div class="bid-item-text">{{ item.item || '（未命名）' }}</div>
              <div v-if="item.detail" class="muted">{{ item.detail }}</div>
              <div class="muted">置信度 {{ item.confidence ?? '-' }}</div>
            </div>
          </div>
        </template>

        <!-- 报价审核（task_type=0） -->
        <template v-else-if="detail.review_data.pricing_section !== undefined">
          <div class="compare-card">
            <div class="compare-label">报价部分</div>
            <div class="compare-content">{{ String(detail.review_data.pricing_section ?? '（无）') }}</div>
          </div>
          <div class="compare-card">
            <div class="compare-label">AI 建议</div>
            <div class="compare-content">{{ String(detail.review_data.ai_suggestion ?? '（无）') }}</div>
          </div>
        </template>

        <!-- 低置信度复核（task_type=1） -->
        <template v-else-if="detail.task_type === 1">
          <div class="detail-block">
            <div class="detail-label">AI 核查结果</div>
            <div class="detail-content">
              <pre>{{ JSON.stringify((detail.review_data.comparison_result ?? {}), null, 2) }}</pre>
            </div>
          </div>
          <div class="detail-block">
            <div class="detail-label">置信度</div>
            <el-progress
              :percentage="Math.round(Number(detail.review_data.confidence ?? 0) * 100)"
              :status="Number(detail.review_data.confidence ?? 0) >= 0.8 ? 'success' : 'warning'"
            />
          </div>
          <div class="detail-block">
            <div class="detail-label">知识库参考</div>
            <div class="detail-content">
              <pre>{{ JSON.stringify(detail.review_data.kb_references ?? [], null, 2) }}</pre>
            </div>
          </div>
        </template>

        <!-- 解析结果确认 / 自检审核（task_type=2/3，内容展示为主） -->
        <template v-else>
          <div class="detail-block">
            <div class="detail-label">审核摘要</div>
            <div class="detail-content">
              {{ String(detail.review_data.summary ?? detail.review_data.project_name ?? '（无摘要）') }}
            </div>
          </div>
          <div class="detail-block">
            <div class="detail-label">完整数据</div>
            <div class="detail-content">
              <pre>{{ JSON.stringify(detail.review_data, null, 2) }}</pre>
            </div>
          </div>
        </template>

        <!-- 审核记录（已审核任务） -->
        <div v-if="detail.review_result !== null" class="detail-block review-record">
          <div class="detail-label">审核记录</div>
          <div class="detail-content">
            结果：{{ detail.review_result === 0 ? '通过' : detail.review_result === 1 ? '驳回' : '修改后通过' }}
            <span v-if="detail.reviewer"> · 审核人：{{ detail.reviewer.display_name || detail.reviewer.username }}</span>
            <span v-if="detail.reviewed_at"> · {{ formatTime(detail.reviewed_at) }}</span>
          </div>
          <div v-if="detail.review_comment" class="detail-content muted">{{ detail.review_comment }}</div>
        </div>
      </template>
    </div>
    </div>
  </div>
</template>

<style scoped>
.review-page {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.filter-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.review-view {
  display: flex;
  flex: 1;
  min-height: 0;
}
.review-detail {
  flex: 1;
  padding: 24px;
  overflow-y: auto;
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
.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;
}
.detail-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
}
.detail-sub {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}
.detail-time {
  font-size: 12px;
  color: var(--text-muted);
}
.detail-actions {
  display: flex;
  gap: 12px;
}
.detail-block {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 16px;
  background: var(--surface);
}
.detail-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 8px;
}
.detail-content {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}
.compare-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 16px;
  background: #f5f3ff;
  border-color: #ddd6fe;
}
.compare-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 8px;
}
.compare-content {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}
.bid-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.bid-item:last-child {
  margin-bottom: 0;
}
.bid-item-human {
  border-color: var(--danger);
  background: #fff5f5;
}
.bid-item-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.bid-item-text {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
  line-height: 1.5;
}
.muted {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.6;
}
.review-record {
  background: #f8fafc;
}
</style>
