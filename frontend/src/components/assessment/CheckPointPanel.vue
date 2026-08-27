<script setup lang="ts">
import type { CheckPoint } from '@/types/assessment'

defineProps<{
  checkPoints: CheckPoint[]
}>()
</script>

<template>
  <div class="panel panel-list">
    <h3 class="panel-title">测评清单</h3>
    <div class="check-point-list">
      <div
        v-for="cp in checkPoints"
        :key="cp.id"
        class="check-point-card"
        :class="{ active: cp.active }"
      >
        <div class="cp-label">{{ cp.label }}</div>
        <div class="cp-code">{{ cp.code }}</div>
      </div>
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

/* ── 测评清单 ── */
.panel-list {
  width: 240px;
  flex-shrink: 0;
}
.check-point-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.check-point-card {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}
.check-point-card:hover {
  border-color: #c7d2fe;
}
.check-point-card.active {
  border-color: var(--primary);
  background: var(--primary-light);
}
.cp-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 4px;
}
.cp-code {
  font-size: 12px;
  color: var(--text-muted);
}
</style>
