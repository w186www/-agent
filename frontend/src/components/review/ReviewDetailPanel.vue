<script setup lang="ts">
defineProps<{
  title: string
  aiContent: string
  humanContent: string
  diffText: string
}>()
</script>

<template>
  <div class="review-detail">
    <div class="detail-header">
      <h2 class="detail-title">{{ title }}</h2>
      <div class="detail-actions">
        <el-button>驳回</el-button>
        <el-button type="primary">通过并继续</el-button>
      </div>
    </div>

    <div class="detail-compare">
      <!-- AI 识别结果 -->
      <div class="compare-card ai-card">
        <div class="compare-label">
          <span class="label-dot ai-dot"></span>
          AI 截图识别
        </div>
        <div class="compare-content">{{ aiContent }}</div>
      </div>

      <!-- 人工记录 -->
      <div class="compare-card human-card">
        <div class="compare-label">
          <span class="label-dot human-dot"></span>
          人工记录
        </div>
        <div class="compare-content">{{ humanContent }}</div>
      </div>
    </div>

    <!-- 差异提示 -->
    <div class="diff-alert">
      <el-icon class="diff-icon"><WarningFilled /></el-icon>
      <div class="diff-text">{{ diffText }}</div>
    </div>
  </div>
</template>

<style scoped>
.review-detail {
  flex: 1;
  padding: 24px;
  overflow-y: auto;
}
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}
.detail-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
}
.detail-actions {
  display: flex;
  gap: 12px;
}
.detail-actions .el-button {
  padding: 10px 24px;
  border-radius: 8px;
}

/* ── 对比卡片 ── */
.detail-compare {
  display: flex;
  gap: 20px;
  margin-bottom: 20px;
}
.compare-card {
  flex: 1;
  padding: 20px;
  border-radius: 10px;
  border: 1px solid var(--border);
}
.ai-card {
  background: #f5f3ff;
  border-color: #ddd6fe;
}
.human-card {
  background: #fffbeb;
  border-color: #fde68a;
}
.compare-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 12px;
}
.label-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.ai-dot {
  background: var(--primary);
}
.human-dot {
  background: var(--warning);
}
.compare-content {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text);
}

/* ── 差异提示 ── */
.diff-alert {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px 20px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 10px;
}
.diff-icon {
  color: var(--warning);
  font-size: 20px;
  flex-shrink: 0;
  margin-top: 2px;
}
.diff-text {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-secondary);
}
</style>
