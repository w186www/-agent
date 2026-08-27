<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { AssessmentRecord } from '@/types/chat'
import { ASSESSMENT_STAGES } from '@/types/chat'
import { getAssessmentRecordApi, getAssessmentRecordsApi } from '@/utils/chat-api'

const props = defineProps<{
  sessionId: number
}>()

const records = ref<AssessmentRecord[]>([])
const loading = ref(false)
const detail = ref<AssessmentRecord | null>(null)
const showDetail = ref(false)

async function loadRecords() {
  loading.value = true
  try {
    const res = await getAssessmentRecordsApi(props.sessionId)
    records.value = res.data.data.items
  } finally {
    loading.value = false
  }
}

async function openDetail(record: AssessmentRecord) {
  try {
    const res = await getAssessmentRecordApi(record.id)
    detail.value = res.data.data
    showDetail.value = true
  } catch {
    ElMessage.error('记录详情加载失败')
  }
}

/** 状态标签（未知状态回退为“未知”） */
function statusLabel(status: number) {
  return ASSESSMENT_STAGES.find((s) => s.status === status)?.label || '未知'
}

/** 置信度进度条颜色 */
function confidenceColor(v: number) {
  if (v >= 0.9) return '#059669'
  if (v >= 0.7) return '#d97706'
  return '#dc2626'
}

watch(() => props.sessionId, () => {
  records.value = []
  loadRecords()
})

onMounted(loadRecords)
</script>

<template>
  <div v-if="records.length" class="task-card assessment-card">
    <div class="card-header">
      <span class="card-title">🔍 测评核查进度</span>
    </div>

    <div
      v-for="record in records"
      :key="record.id"
      class="record-row"
      @click="openDetail(record)"
    >
      <div class="record-code">{{ record.checklist_code }}</div>
      <div class="record-main">
        <div class="record-name">{{ record.checklist_name }}</div>
        <div class="record-status" :class="`status-${record.status}`">
          {{ statusLabel(record.status) }}
        </div>
      </div>
    </div>

    <!-- 详情弹窗 -->
    <el-dialog v-model="showDetail" title="测评核查详情" width="640px">
      <template v-if="detail">
        <div class="dialog-head">
          <span class="dialog-code">{{ detail.checklist_code }}</span>
          <span class="dialog-name">{{ detail.checklist_name }}</span>
          <span class="dialog-status">{{ statusLabel(detail.status) }}</span>
        </div>

        <div class="dialog-section">
          <div class="dialog-title">置信度</div>
          <el-progress
            :percentage="Math.round(detail.confidence * 100)"
            :color="confidenceColor(detail.confidence)"
          />
        </div>

        <div class="dialog-section">
          <div class="dialog-title">VLM 识别结果</div>
          <pre class="json-block">{{ JSON.stringify(detail.vlm_analysis ?? {}, null, 2) }}</pre>
        </div>

        <div class="dialog-section">
          <div class="dialog-title">人工记录</div>
          <div class="text-block">{{ detail.human_record || '（无人工记录）' }}</div>
        </div>

        <div class="dialog-section">
          <div class="dialog-title">比对结果</div>
          <pre class="json-block">{{ JSON.stringify(detail.comparison_result ?? {}, null, 2) }}</pre>
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
  margin-bottom: 10px;
}
.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.record-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}
.record-row:hover {
  background: #f8f9fb;
}
.record-code {
  font-size: 12px;
  color: var(--text-muted);
  background: #f1f3f5;
  padding: 2px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}
.record-main {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
}
.record-name {
  font-size: 13px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.record-status {
  font-size: 12px;
  flex-shrink: 0;
}
.status-0, .status-1, .status-2 { color: #d97706; }
.status-3 { color: #059669; }
.status-4 { color: #d97706; }
.status-5 { color: #059669; }
.status-6 { color: #dc2626; }

/* 弹窗 */
.dialog-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.dialog-code {
  font-size: 13px;
  color: var(--text-muted);
  background: #f1f3f5;
  padding: 2px 8px;
  border-radius: 4px;
}
.dialog-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.dialog-status {
  margin-left: auto;
  font-size: 13px;
  color: var(--primary);
}
.dialog-section {
  margin-bottom: 16px;
}
.dialog-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}
.json-block {
  margin: 0;
  padding: 10px 12px;
  background: #f8f9fb;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--text-secondary);
}
.text-block {
  padding: 10px 12px;
  background: #f8f9fb;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
}
</style>
