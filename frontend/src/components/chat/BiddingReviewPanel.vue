<script setup lang="ts">
/**
 * 招投标 HITL 审核面板（合并进对话助手后由 ChatView 传入共享状态）。
 * 只负责渲染与内部编辑草稿，提交动作统一 emit 给父组件执行（resumeHitl / submitReviewApi）。
 */
import { computed, ref, watch, type PropType } from 'vue'
import { ElMessage } from 'element-plus'
import type { HitlPayload } from '@/utils/streamChat'
import type { WorkSession } from '@/composables/useSessionStreamSender'
import { submitReviewApi } from '@/utils/chat-api'

const props = defineProps({
  /** 待审核任务队列（由父组件 useSessionStreamSender 的 hitlQueue 传入） */
  hitlQueue: { type: Array as PropType<HitlPayload[]>, required: true },
  /** 是否处于流式输出（提交按钮加载态） */
  isSending: { type: Boolean, default: false },
  /** 当前招投标会话（resume 目标） */
  session: { type: Object as PropType<WorkSession | null>, default: null },
})

const emit = defineEmits<{
  (e: 'confirmParsed', review: HitlPayload): void
  (e: 'selfcheck', review: HitlPayload, action: 'approve' | 'reject' | 'modified', modifiedSections?: Record<string, string>): void
  (e: 'removeReview', review: HitlPayload): void
}>()

// ── 待审核任务分类 ──
/** 待解析结果确认的 HITL 任务（task_type=2） */
const parsedReviews = computed(() => props.hitlQueue.filter((h) => h.task_type === 2))
/** 自检审核 HITL 任务（task_type=3） */
const selfcheckReviews = computed(() => props.hitlQueue.filter((h) => h.task_type === 3))
/** 投标文件审核（task_type=0 且 review_data.bidding_review=true） */
const biddingReviewReviews = computed(() =>
  props.hitlQueue.filter(
    (h) => h.task_type === 0 && !!(h.review_data as Record<string, unknown>)?.bidding_review,
  ),
)
/** 报价审核（task_type=0 且非投标文件审核） */
const pricingReviews = computed(() =>
  props.hitlQueue.filter(
    (h) => h.task_type === 0 && !(h.review_data as Record<string, unknown>)?.bidding_review,
  ),
)

// ── 解析确认卡片数据结构（与后端 _parse_review_data 字段对齐）──
interface ParsedReviewData {
  project_name?: string
  budget?: string | number | null
  deadline?: string | null
  qualification_requirements?: string[]
  scoring_items?: string[]
  disqualification_items?: string[]
}

function parsedData(review: HitlPayload): ParsedReviewData {
  return (review.review_data ?? {}) as ParsedReviewData
}

// ── 报价审核数据结构（review_data 子集）──
interface BiddingReviewData {
  pricing_section?: string
  ai_suggestion?: string
}

function reviewData(review: HitlPayload): BiddingReviewData {
  return (review.review_data ?? {}) as BiddingReviewData
}

// ── 自检审核（task_type=3）──
interface SelfcheckItem {
  item?: string
  type?: string
  status?: string
  detail?: string
}

interface SelfcheckCompliance {
  overall_status?: string
  summary?: string
  [group: string]: unknown
}

interface SelfcheckReviewData {
  bidding_sections?: Record<string, string>
  compliance_result?: SelfcheckCompliance
  summary?: string
}

function selfcheckData(review: HitlPayload): SelfcheckReviewData {
  return (review.review_data ?? {}) as SelfcheckReviewData
}

/** 自检检查分组顺序与标题（compliance_result 三个维度） */
const CHECK_GROUPS = [
  { key: 'disqualification_check', title: '废标项检查' },
  { key: 'format_check', title: '格式检查' },
  { key: 'typo_check', title: '错别字检查' },
]

/** 投标内容编辑草稿（key=review_task_id，value=各部分文本，供"修改后通过"提交） */
const selfcheckDrafts = ref<Record<number, Record<string, string>>>({})

/** 初始化某审核任务的编辑草稿（首次读取时以服务端投标内容填充） */
function draftOf(review: HitlPayload): Record<string, string> {
  const key = review.review_task_id
  if (!selfcheckDrafts.value[key]) {
    const sections: Record<string, string> = {}
    for (const [k, value] of Object.entries(selfcheckData(review).bidding_sections ?? {})) {
      sections[k] = typeof value === 'string' ? value : JSON.stringify(value)
    }
    selfcheckDrafts.value[key] = sections
  }
  return selfcheckDrafts.value[key]
}

/** 投标部分中文名（与 generate_bidding 的 section 约定对齐） */
function sectionLabel(key: string): string {
  const labels: Record<string, string> = {
    company_profile: '公司简介',
    qualification: '资质响应',
    project_team: '项目团队',
    pricing: '报价（待人工审核）',
  }
  return labels[key] || key
}

/** 自检结果分组（剔除空维度），供三色标注渲染 */
function selfcheckGroups(review: HitlPayload): { title: string; items: SelfcheckItem[] }[] {
  const compliance = selfcheckData(review).compliance_result ?? {}
  return CHECK_GROUPS.filter((g) => Array.isArray(compliance[g.key]))
    .map((g) => ({ title: g.title, items: compliance[g.key] as SelfcheckItem[] }))
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

// 自检审核卡片切换时同步草稿（新一轮驳回重生成会携带新的 review_task_id）
watch(
  () => selfcheckReviews.value.map((r) => r.review_task_id).join(','),
  () => {
    const active = new Set(selfcheckReviews.value.map((r) => r.review_task_id))
    for (const key of Object.keys(selfcheckDrafts.value)) {
      const id = Number(key)
      if (!active.has(id)) delete selfcheckDrafts.value[id]
    }
    for (const review of selfcheckReviews.value) draftOf(review)
  },
  { immediate: true },
)

// ── 投标文件审核（task_type=0 + bidding_review）──
interface BiddingReviewItem {
  item?: string
  type?: string
  status?: string
  detail?: string
  confidence?: number
  need_human?: boolean
}

interface BiddingReviewData {
  bidding_review?: boolean
  overall_status?: string
  items?: BiddingReviewItem[]
  summary?: string
}

function biddingReviewData(review: HitlPayload): BiddingReviewData {
  return (review.review_data ?? {}) as BiddingReviewData
}

/** 投标文件审核逐项人工确认结果（key=review_task_id，value={itemIndex: pass|reject|skip}） */
const biddingReviewDecisions = ref<Record<number, Record<number, 'pass' | 'reject' | 'skip'>>>({})

function decisionsOf(reviewId: number): Record<number, 'pass' | 'reject' | 'skip'> {
  if (!biddingReviewDecisions.value[reviewId]) {
    biddingReviewDecisions.value[reviewId] = {}
  }
  return biddingReviewDecisions.value[reviewId]
}

function setDecision(reviewId: number, index: number, decision: 'pass' | 'reject' | 'skip') {
  decisionsOf(reviewId)[index] = decision
}

/** need_human 项是否已全部确认（未全部确认前禁用"生成审核报告"） */
function allNeedHumanConfirmed(review: HitlPayload): boolean {
  const items = biddingReviewData(review).items ?? []
  const decisions = decisionsOf(review.review_task_id)
  return items.every((item, i) => !item.need_human || decisions[i] !== undefined)
}

// 审核任务移除后清理本地决策草稿（新一轮审核带新的 review_task_id）
watch(
  () => biddingReviewReviews.value.map((r) => r.review_task_id).join(','),
  () => {
    const active = new Set(biddingReviewReviews.value.map((r) => r.review_task_id))
    for (const key of Object.keys(biddingReviewDecisions.value)) {
      if (!active.has(Number(key))) delete biddingReviewDecisions.value[Number(key)]
    }
  },
)

// ── 审核提交动作（面板内部执行，成功后通知父组件移除任务）──

/** 报价审核：通过/驳回/修改后通过，直接提交审核任务 */
async function handleSubmitReview(review: HitlPayload, action: 'approve' | 'reject' | 'modified') {
  try {
    await submitReviewApi(review.review_task_id, { action })
    ElMessage.success(
      action === 'approve' ? '审核通过' : action === 'reject' ? '已驳回' : '已修改后通过',
    )
    emit('removeReview', review)
  } catch {
    /* 错误提示由 request 拦截器统一处理 */
  }
}

/** 生成投标文件审核报告：逐项确认意见写入 comment 提交 */
async function handleGenerateReviewReport(review: HitlPayload) {
  const decisions = biddingReviewDecisions.value[review.review_task_id] ?? {}
  const comment = JSON.stringify({ decisions }, null, 2)
  try {
    await submitReviewApi(review.review_task_id, { action: 'approve', comment })
    ElMessage.success('审核报告已生成')
    emit('removeReview', review)
  } catch {
    /* 错误提示由 request 拦截器统一处理 */
  }
}
</script>

<template>
  <div class="review-panel">
    <!-- 解析确认（HITL task_type=2） -->
    <div class="panel-title">解析确认</div>
    <div v-if="!parsedReviews.length" class="empty-state">
      <div class="empty-text">暂无待确认的解析结果</div>
    </div>
    <template v-else>
      <div v-for="review in parsedReviews" :key="review.source_id" class="review-card">
        <el-alert title="请确认招标解析结果" type="info" :closable="false" show-icon />
        <div class="review-block">
          <div class="review-label">项目名称</div>
          <div class="review-content">
            {{ parsedData(review).project_name || '（无）' }}
          </div>
        </div>
        <div class="review-block">
          <div class="review-label">预算</div>
          <div class="review-content">
            {{ parsedData(review).budget ?? '（无）' }}
          </div>
        </div>
        <div class="review-block">
          <div class="review-label">截止日期</div>
          <div class="review-content">
            {{ parsedData(review).deadline ?? '（无）' }}
          </div>
        </div>
        <div class="review-block">
          <div class="review-label">资格要求</div>
          <div class="review-content">
            <template v-if="parsedData(review).qualification_requirements?.length">
              <div v-for="(item, i) in parsedData(review).qualification_requirements" :key="i">· {{ item }}</div>
            </template>
            <template v-else>（无）</template>
          </div>
        </div>
        <div class="review-block">
          <div class="review-label">评分表</div>
          <div class="review-content">
            <template v-if="parsedData(review).scoring_items?.length">
              <div v-for="(item, i) in parsedData(review).scoring_items" :key="i">· {{ item }}</div>
            </template>
            <template v-else>（无）</template>
          </div>
        </div>
        <div class="review-block">
          <div class="review-label">废标项</div>
          <div class="review-content">
            <template v-if="parsedData(review).disqualification_items?.length">
              <div v-for="(item, i) in parsedData(review).disqualification_items" :key="i">· {{ item }}</div>
            </template>
            <template v-else>（无）</template>
          </div>
        </div>
        <div class="review-actions">
          <el-button
            type="primary"
            size="small"
            :loading="isSending"
            @click="emit('confirmParsed', review)"
          >
            确认合适，开始编写
          </el-button>
        </div>
      </div>
    </template>

    <!-- 自检审核（HITL task_type=3） -->
    <div class="panel-title panel-title-gap">自检审核</div>
    <div v-if="!selfcheckReviews.length" class="empty-state">
      <div class="empty-text">暂无待审核的自检结果</div>
    </div>
    <template v-else>
      <div
        v-for="review in selfcheckReviews"
        :key="review.review_task_id"
        class="review-card selfcheck-card"
      >
        <el-alert title="请审核投标文件与自检结果" type="info" :closable="false" show-icon />
        <!-- 上半区：投标内容（可编辑，供"修改后通过"提交） -->
        <div class="review-block">
          <div class="review-label">投标内容（可编辑）</div>
          <div v-for="(value, key) in selfcheckDrafts[review.review_task_id]" :key="key" class="section-edit">
            <div class="section-key">{{ sectionLabel(key) }}</div>
            <el-input
              v-model="selfcheckDrafts[review.review_task_id][key]"
              type="textarea"
              :rows="3"
              resize="none"
            />
          </div>
        </div>
        <!-- 下半区：自检结果（pass/warning/danger 三色标注） -->
        <div class="review-block">
          <div class="review-label">
            自检结果（{{ selfcheckData(review).summary || '未汇总' }}）
          </div>
          <div v-if="!selfcheckGroups(review).length" class="review-content">（无检查项）</div>
          <div v-for="group in selfcheckGroups(review)" :key="group.title" class="check-group">
            <div class="check-group-title">{{ group.title }}</div>
            <div v-for="(item, i) in group.items" :key="i" class="check-item">
              <el-tag size="small" :type="statusTagType(item.status)" effect="plain">
                {{ statusText(item.status) }}
              </el-tag>
              <span class="check-item-text">{{ item.item || '（未命名）' }}</span>
              <div v-if="item.detail" class="check-item-detail">{{ item.detail }}</div>
            </div>
          </div>
        </div>
        <div class="review-actions">
          <el-button
            type="success"
            size="small"
            :loading="isSending"
            @click="emit('selfcheck', review, 'approve')"
          >
            通过
          </el-button>
          <el-button
            type="danger"
            size="small"
            :loading="isSending"
            @click="emit('selfcheck', review, 'reject')"
          >
            驳回（重新生成）
          </el-button>
          <el-button
            size="small"
            :loading="isSending"
            @click="emit('selfcheck', review, 'modified', draftOf(review))"
          >
            修改后通过
          </el-button>
        </div>
      </div>
    </template>

    <!-- 投标文件审核（task_type=0 + bidding_review） -->
    <div class="panel-title panel-title-gap">投标文件审核</div>
    <div v-if="!biddingReviewReviews.length" class="empty-state">
      <div class="empty-text">暂无待审核的投标文件</div>
    </div>
    <template v-else>
      <div
        v-for="review in biddingReviewReviews"
        :key="review.review_task_id"
        class="review-card bid-review-card"
      >
        <el-alert title="请逐项确认投标文件审核结果" type="warning" :closable="false" show-icon />
        <div class="review-block">
          <div class="review-label">
            审核汇总：{{ biddingReviewData(review).summary || '未汇总' }}
          </div>
          <div v-if="!biddingReviewData(review).items?.length" class="review-content">
            （无检查项）
          </div>
          <div
            v-for="(item, i) in biddingReviewData(review).items ?? []"
            :key="i"
            class="bid-item"
            :class="{ 'bid-item-human': item.need_human }"
          >
            <div class="bid-item-top">
              <el-tag size="small" :type="statusTagType(item.status)" effect="plain">
                {{ statusText(item.status) }}
              </el-tag>
              <span class="bid-item-type">{{ item.type || '检查项' }}</span>
              <el-tag v-if="item.need_human" size="small" type="danger" effect="plain">需人工确认</el-tag>
            </div>
            <div class="bid-item-text">{{ item.item || '（未命名）' }}</div>
            <div v-if="item.detail" class="bid-item-detail">{{ item.detail }}</div>
            <div class="bid-item-meta">置信度 {{ item.confidence ?? '-' }}</div>
            <div v-if="item.need_human" class="bid-item-actions">
              <el-button size="small" type="success" plain @click="setDecision(review.review_task_id, i, 'pass')">
                确认通过
              </el-button>
              <el-button size="small" type="danger" plain @click="setDecision(review.review_task_id, i, 'reject')">
                确认不通过
              </el-button>
              <el-button size="small" plain @click="setDecision(review.review_task_id, i, 'skip')">
                跳过
              </el-button>
            </div>
            <div v-else-if="decisionsOf(review.review_task_id)[i]" class="bid-item-decided">
              已确认：{{
                decisionsOf(review.review_task_id)[i] === 'pass'
                  ? '通过'
                  : decisionsOf(review.review_task_id)[i] === 'reject'
                    ? '不通过'
                    : '跳过'
              }}
            </div>
          </div>
        </div>
        <div class="review-actions">
          <el-button
            type="primary"
            size="small"
            :disabled="!allNeedHumanConfirmed(review)"
            @click="handleGenerateReviewReport(review)"
          >
            生成审核报告
          </el-button>
        </div>
      </div>
    </template>

    <!-- 报价审核（task_type=0） -->
    <div class="panel-title panel-title-gap">报价审核</div>
    <div v-if="!pricingReviews.length" class="empty-state">
      <div class="empty-text">暂无待审核报价</div>
    </div>
    <template v-else>
      <div
        v-for="review in pricingReviews"
        :key="review.review_task_id"
        class="review-card"
      >
        <el-alert title="需要人工审核" type="warning" :closable="false" show-icon />
        <div class="review-block">
          <div class="review-label">报价部分</div>
          <div class="review-content">
            {{ reviewData(review).pricing_section || '（无）' }}
          </div>
        </div>
        <div class="review-block">
          <div class="review-label">AI 建议</div>
          <div class="review-content ai-suggestion">
            {{ reviewData(review).ai_suggestion || '（无）' }}
          </div>
        </div>
        <div class="review-actions">
          <el-button type="success" size="small" :loading="isSending" @click="handleSubmitReview(review, 'approve')">通过</el-button>
          <el-button type="danger" size="small" :loading="isSending" @click="handleSubmitReview(review, 'reject')">驳回</el-button>
          <el-button size="small" :loading="isSending" @click="handleSubmitReview(review, 'modified')">修改后通过</el-button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.review-panel {
  width: 300px;
  flex-shrink: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  overflow-y: auto;
}
.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 16px;
}
.panel-title-gap {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 13px;
  padding: 8px 0;
}
.empty-text {
  color: var(--text-muted);
}
.review-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
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
.ai-suggestion {
  color: var(--primary);
}
.review-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.selfcheck-card {
  gap: 10px;
}
.section-edit {
  margin-bottom: 8px;
}
.section-edit:last-child {
  margin-bottom: 0;
}
.section-key {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.section-edit :deep(.el-textarea__inner) {
  font-size: 12px;
  line-height: 1.5;
}
.check-group {
  margin-bottom: 10px;
}
.check-group:last-child {
  margin-bottom: 0;
}
.check-group-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 6px;
}
.check-item {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 6px;
  padding: 3px 0;
}
.check-item-text {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: var(--text);
  line-height: 1.5;
}
.check-item-detail {
  width: 100%;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
  padding-left: 2px;
}
.bid-review-card {
  gap: 10px;
}
.bid-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
  background: #fff;
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
  gap: 6px;
  margin-bottom: 4px;
}
.bid-item-type {
  font-size: 12px;
  color: var(--text-muted);
}
.bid-item-text {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  line-height: 1.5;
}
.bid-item-detail {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
  margin-top: 2px;
}
.bid-item-meta {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}
.bid-item-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.bid-item-decided {
  font-size: 12px;
  color: var(--success);
  margin-top: 6px;
}
</style>
