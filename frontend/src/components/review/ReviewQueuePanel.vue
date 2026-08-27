<script setup lang="ts">
import type { ReviewItem } from '@/types/review'

defineProps<{
  items: ReviewItem[]
}>()

const emit = defineEmits<{
  (e: 'select', id: number): void
}>()
</script>

<template>
  <div class="review-queue">
    <div class="queue-header">
      <h3 class="queue-title">待审队列</h3>
      <el-badge :value="items.length" class="queue-badge" />
    </div>
    <div class="queue-list">
      <div
        v-for="item in items"
        :key="item.id"
        class="queue-item"
        :class="{ active: item.active }"
        @click="emit('select', item.id)"
      >
        <div class="queue-item-top">
          <el-tag
            :type="item.category === '测评核查' ? 'primary' : 'warning'"
            effect="plain"
            size="small"
          >
            {{ item.category }}
          </el-tag>
          <span class="queue-dot"></span>
        </div>
        <div class="queue-item-title">{{ item.title }}</div>
        <div class="queue-item-meta">{{ item.confidence }} · {{ item.time }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.review-queue {
  width: 300px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
  padding: 20px;
  overflow-y: auto;
}
.queue-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.queue-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}
.queue-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.queue-item {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
}
.queue-item:hover {
  border-color: #c7d2fe;
}
.queue-item.active {
  border-color: var(--primary);
  background: var(--primary-light);
}
.queue-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.queue-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--warning);
}
.queue-item-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 6px;
}
.queue-item-meta {
  font-size: 12px;
  color: var(--text-muted);
}
</style>
