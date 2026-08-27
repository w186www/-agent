<script setup lang="ts">
import type { ResultItem } from '@/types/assessment'

defineProps<{
  results: ResultItem[]
}>()
</script>

<template>
  <div class="panel panel-result">
    <h3 class="panel-title">核查结果</h3>
    <div class="result-list">
      <div
        v-for="r in results"
        :key="r.id"
        class="result-card"
        :class="r.status"
      >
        <div class="result-label">{{ r.label }}</div>
        <div class="result-value">{{ r.value }}</div>
        <div v-if="r.status === 'warn'" class="result-bar">
          <div class="result-bar-fill" style="width: 40%"></div>
        </div>
      </div>
    </div>
    <div class="confidence-card">
      <div class="conf-label">置信度</div>
      <div class="conf-value">62%</div>
      <el-icon class="conf-icon"><WarningFilled /></el-icon>
      <div class="conf-hint">建议人工复核</div>
    </div>
  </div>
</template>

<style scoped>
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}
.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 16px;
}

/* ── 核查结果 ── */
.panel-result {
  flex: 1;
  min-width: 0;
}
.result-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 16px;
}
.result-card {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.result-card.warn {
  border-color: var(--warning);
  background: #fffbeb;
}
.result-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.result-value {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
}
.result-bar {
  height: 4px;
  background: #e5e7eb;
  border-radius: 2px;
  margin-top: 8px;
  overflow: hidden;
}
.result-bar-fill {
  height: 100%;
  background: var(--warning);
  border-radius: 2px;
}

/* ── 置信度 ── */
.confidence-card {
  padding: 16px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 8px;
  text-align: center;
}
.conf-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}
.conf-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 4px;
}
.conf-icon {
  color: var(--warning);
  font-size: 18px;
  margin-bottom: 4px;
}
.conf-hint {
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
