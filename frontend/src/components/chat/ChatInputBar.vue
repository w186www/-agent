<script setup lang="ts">
import { ref } from 'vue'

const modelValue = defineModel<string>({ default: '' })

const emit = defineEmits<{
  (e: 'send', text: string): void
}>()

function onInput(value: string) {
  modelValue.value = value
}

function handleSend() {
  const text = modelValue.value.trim()
  if (!text) return
  emit('send', text)
  modelValue.value = ''
}
</script>

<template>
  <div class="chat-input-bar">
    <el-input
      :model-value="modelValue"
      placeholder="输入消息，Enter 发送…"
      class="chat-input"
      @update:model-value="onInput"
      @keydown.enter.exact.prevent="handleSend"
    />
    <el-button type="primary" class="send-btn" @click="handleSend">
      <el-icon><ArrowRight /></el-icon>
      发送
    </el-button>
  </div>
</template>

<style scoped>
.chat-input-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 24px;
  background: var(--surface);
  border-top: 1px solid var(--border);
}
.chat-input {
  flex: 1;
}
.chat-input :deep(.el-input__wrapper) {
  border-radius: 24px;
  padding: 4px 16px;
}
.send-btn {
  border-radius: 24px;
  padding: 10px 24px;
}
</style>
