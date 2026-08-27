<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { BiddingTask } from '@/types/chat'
import { BIDDING_STAGES } from '@/types/chat'
import { getBiddingTaskApi, getBiddingTasksApi } from '@/utils/chat-api'

const props = defineProps<{
  sessionId: number
}>()

const task = ref<BiddingTask | null>(null)
const loading = ref(false)
const detail = ref<BiddingTask | null>(null)
const showDetail = ref(false)

/** 当前阶段在流程中的下标（-1 表示未知状态） */
function currentIndex(status: number) {
  return BIDDING_STAGES.findIndex((s) => s.status === status)
}

async function loadTask() {
  loading.value = true
  try {
    const res = await getBiddingTasksApi(props.sessionId)
    task.value = res.data.data
  } finally {
    loading.value = false
  }
}

async function openDetail() {
  if (!task.value) return
  try {
    const res = await getBiddingTaskApi(task.value.id)
    detail.value = res.data.data
    showDetail.value = true
  } catch {
    ElMessage.error('任务详情加载失败')
  }
}

/** 合规结果颜色映射 */
function levelClass(level: string) {
  return { pass: 'level-pass', warning: 'level-warning', danger: 'level-danger' }[level] || ''
}

watch(() => props.sessionId, () => {
  task.value = null
  loadTask()
})

onMounted(loadTask)
</script>

<template>
  <div v-if="task" class="task-card bidding-card">
    <div class="card-header">
      <span class="card-title">📄 招投标进度</span>
      <el-button link type="primary" size="small" @click="openDetail">查看详情</el-button>
    </div>

    <div class="stage-flow">
      <div
        v-for="(stage, i) in BIDDING_STAGES"
        :key="stage.status"
        class="stage"
        :class="{
          done: currentIndex(task.status) > i,
          active: currentIndex(task.status) === i,
        }"
      >
        <span class="stage-dot"></span>
        <span class="stage-label">{{ stage.label }}</span>
      </div>
    </div>

    <div v-if="task.tender_title" class="task-title">{{ task.tender_title }}</div>

    <!-- 详情弹窗 -->
    <el-dialog v-model="showDetail" title="招投标任务详情" width="640px">
      <template v-if="detail">
        <div class="dialog-section">
          <div class="dialog-title">投标文件内容</div>
          <div v-for="(content, key) in detail.bidding_sections || {}" :key="key" class="section-item">
            <div class="section-name">{{ key }}</div>
            <div class="section-content">{{ content }}</div>
          </div>
        </div>
        <div class="dialog-section">
          <div class="dialog-title">废标检查结果</div>
          <div v-for="(item, i) in detail.compliance_result || []" :key="i" class="check-item">
            <span class="level-badge" :class="levelClass(item.status)">{{ item.status }}</span>
            <span class="check-name">{{ item.item }}</span>
            <span v-if="item.type" class="check-type">{{ item.type }}</span>
            <span v-if="item.detail" class="check-desc">{{ item.detail }}</span>
          </div>
          <div v-if="!detail.compliance_result?.length" class="empty-hint">暂无检查结果</div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.task-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  background: var(--surface);
  margin-bottom: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.stage-flow {
  display: flex;
  align-items: flex-start;
  margin-bottom: 10px;
}
.stage {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  position: relative;
}
.stage::after {
  content: '';
  position: absolute;
  top: 4px;
  left: 50%;
  width: 100%;
  height: 2px;
  background: var(--border);
}
.stage:last-child::after {
  display: none;
}
.stage.done::after {
  background: var(--primary);
}
.stage-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--border);
  z-index: 1;
}
.stage.done .stage-dot {
  background: var(--primary);
}
.stage.active .stage-dot {
  background: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-light);
}
.stage-label {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}
.stage.done .stage-label,
.stage.active .stage-label {
  color: var(--primary);
  font-weight: 600;
}
.task-title {
  font-size: 13px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 弹窗 */
.dialog-section {
  margin-bottom: 18px;
}
.dialog-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 10px;
}
.section-item {
  margin-bottom: 10px;
}
.section-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 4px;
}
.section-content {
  font-size: 13px;
  color: var(--text);
  padding: 8px 10px;
  background: #f8f9fb;
  border-radius: 6px;
  line-height: 1.6;
}
.check-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--border);
}
.check-item:last-child {
  border-bottom: none;
}
.level-badge {
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}
.level-pass {
  background: #ecfdf5;
  color: #059669;
}
.level-warning {
  background: #fffbeb;
  color: #d97706;
}
.level-danger {
  background: #fef2f2;
  color: #dc2626;
}
.check-name {
  font-size: 13px;
  color: var(--text);
}
.check-type {
  font-size: 12px;
  color: var(--text-muted);
  background: #f1f3f5;
  padding: 1px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}
.check-desc {
  font-size: 12px;
  color: var(--text-muted);
}
.empty-hint {
  font-size: 13px;
  color: var(--text-muted);
}
</style>
