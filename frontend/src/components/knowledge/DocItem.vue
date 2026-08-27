<script setup lang="ts">
import type { DocItem as Doc } from '@/types/knowledge'

defineProps<{
  doc: Doc
}>()
</script>

<template>
  <div class="doc-item">
    <el-icon class="doc-icon"><Document /></el-icon>
    <div class="doc-info">
      <div class="doc-title">{{ doc.title }}</div>
      <div class="doc-meta">{{ doc.date }} · {{ doc.size }}</div>
    </div>
    <el-button text type="primary" size="small">查看</el-button>
  </div>
</template>

<style scoped>
.doc-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
.doc-icon {
  font-size: 24px;
  color: var(--primary);
  flex-shrink: 0;
}
.doc-info {
  flex: 1;
  min-width: 0;
}
.doc-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-meta {
  font-size: 12px;
  color: var(--text-muted);
}
</style>
