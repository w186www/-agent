<script setup lang="ts">
import type { Step } from '@/types/bidding'

defineProps<{
  steps: Step[]
}>()
</script>

<template>
  <div class="steps-section">
    <div class="steps-header">
      <h2 class="section-title">招投标工作台</h2>
      <el-tag type="primary" effect="plain">商务</el-tag>
    </div>
    <div class="steps-list">
      <div
        v-for="(step, idx) in steps"
        :key="step.id"
        class="step-item"
      >
        <div class="step-connector" v-if="idx > 0"></div>
        <div
          class="step-circle"
          :class="step.status"
        >
          {{ step.status === 'done' ? '✓' : step.id }}
        </div>
        <span
          class="step-label"
          :class="step.status"
        >
          {{ step.label }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.steps-section {
  flex: 1;
  background: var(--surface);
  border-radius: var(--radius);
  padding: 24px;
  border: 1px solid var(--border);
}
.steps-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}
.section-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
}
.steps-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.step-item {
  display: flex;
  align-items: center;
  gap: 12px;
  position: relative;
  padding: 8px 0;
}
.step-connector {
  position: absolute;
  left: 17px;
  top: -12px;
  width: 2px;
  height: 20px;
  background: var(--border);
}
.step-circle {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
  background: #f3f4f6;
  color: var(--text-muted);
}
.step-circle.done {
  background: var(--success);
  color: #fff;
}
.step-circle.active {
  background: var(--primary);
  color: #fff;
}
.step-label {
  font-size: 15px;
  color: var(--text-muted);
}
.step-label.done {
  color: var(--text);
}
.step-label.active {
  color: var(--primary);
  font-weight: 500;
}
</style>
