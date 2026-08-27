<script setup lang="ts">
import { ref } from 'vue'
import type { ToolCall } from '@/types/chat'

defineProps<{
  toolCalls: ToolCall[]
}>()

// 已展开的工具调用序号集合
const expanded = ref<Set<number>>(new Set())

function toggle(index: number) {
  const next = new Set(expanded.value)
  if (next.has(index)) {
    next.delete(index)
  } else {
    next.add(index)
  }
  expanded.value = next
}

/** 工具返回结果摘要：截取前 200 字符 */
function summarize(value: unknown): string {
  if (value === null || value === undefined) return ''
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > 200 ? `${text.slice(0, 200)}…` : text
}
</script>

<template>
  <div class="tool-calls">
    <div
      v-for="(call, index) in toolCalls"
      :key="index"
      class="tool-call"
    >
      <div class="tool-call-header" @click="toggle(index)">
        <span class="tool-icon">⚙</span>
        <span class="tool-name">{{ call.name }}</span>
        <span v-if="call.duration_ms !== undefined" class="tool-duration">
          {{ call.duration_ms }}ms
        </span>
        <span class="tool-arrow">{{ expanded.has(index) ? '▾' : '▸' }}</span>
      </div>
      <div v-if="expanded.has(index)" class="tool-call-body">
        <div class="tool-section">
          <div class="tool-section-title">参数</div>
          <pre class="tool-json">{{ JSON.stringify(call.arguments ?? {}, null, 2) }}</pre>
        </div>
        <div v-if="call.result !== undefined" class="tool-section">
          <div class="tool-section-title">返回结果</div>
          <pre class="tool-json">{{ summarize(call.result) }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-calls {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
}
.tool-call {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.tool-call-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--surface);
  cursor: pointer;
  font-size: 13px;
  user-select: none;
}
.tool-call-header:hover {
  background: #f9fafb;
}
.tool-icon {
  color: var(--primary);
}
.tool-name {
  font-weight: 600;
  color: var(--text);
}
.tool-duration {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-muted);
}
.tool-arrow {
  color: var(--text-muted);
  font-size: 12px;
}
.tool-call-body {
  padding: 10px 12px;
  background: #fafbfc;
}
.tool-section {
  margin-bottom: 8px;
}
.tool-section:last-child {
  margin-bottom: 0;
}
.tool-section-title {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.tool-json {
  margin: 0;
  padding: 8px 10px;
  background: #f1f3f5;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
  color: var(--text-secondary);
}
</style>
