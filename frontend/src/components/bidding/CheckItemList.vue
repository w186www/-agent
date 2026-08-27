<script setup lang="ts">
import type { CheckItem } from '@/types/bidding'

defineProps<{
  items: CheckItem[]
}>()

const statusConfig: Record<string, { label: string; type: string }> = {
  pass: { label: '通过', type: 'success' },
  warn: { label: '注意', type: 'warning' },
  fail: { label: '废标', type: 'danger' },
}

const statusIcon: Record<string, string> = {
  pass: 'Check',
  warn: 'Warning',
  fail: 'Close',
}
</script>

<template>
  <div class="checks-section">
    <div
      v-for="item in items"
      :key="item.id"
      class="check-item"
      :class="item.status"
    >
      <div class="check-left">
        <el-icon :class="`check-icon-${item.status}`">
          <component :is="statusIcon[item.status]" />
        </el-icon>
        <span class="check-text">{{ item.text }}</span>
      </div>
      <el-tag
        :type="statusConfig[item.status].type as any"
        effect="plain"
        size="small"
      >
        {{ statusConfig[item.status].label }}
      </el-tag>
    </div>
  </div>
</template>

<style scoped>
.checks-section {
  width: 380px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.check-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  border-left: 4px solid var(--border);
}
.check-item.pass {
  border-left-color: var(--success);
}
.check-item.warn {
  border-left-color: var(--warning);
}
.check-item.fail {
  border-left-color: var(--danger);
}
.check-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}
.check-text {
  font-size: 14px;
  color: var(--text);
}
.check-icon-pass {
  color: var(--success);
  font-size: 18px;
}
.check-icon-warn {
  color: var(--warning);
  font-size: 18px;
}
.check-icon-fail {
  color: var(--danger);
  font-size: 18px;
}
</style>
