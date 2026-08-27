<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ChatMessage } from '@/types/chat'
import MsgToolCalls from './MsgToolCalls.vue'

const props = defineProps<{
  message: ChatMessage
}>()

// 文件提取文本折叠展开
const fileExpanded = ref(false)
// 引用来源折叠展开
const sourceExpanded = ref(false)
// 思考过程（工具调用 / JSON 过程数据）折叠展开：默认收起，与最终回复分开单独查看
const thinkingExpanded = ref(false)

/** 格式化消息时间（HH:MM） */
function formatTime(ts: number): string {
  const d = new Date(ts * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 相似度展示：score 为 0-1 余弦相似度，转百分比 */
function formatScore(score: number | null): string {
  if (score == null) return ''
  return `相似度 ${(score * 100).toFixed(1)}%`
}

/** 内容拆分结果：正文（自然语言） + JSON 块（模型复述的工具结果/过程数据） */
interface ContentSplit {
  text: string
  jsonBlocks: string[]
}

/**
 * 把 AI 回复中独立的 JSON 对象/数组块（含 Markdown ```json 代码块）剥离出来，
 * 收进思考卡片单独查看，正文只保留自然语言。逐字符括号配对，跳过字符串内的大括号，
 * 剥离前用 JSON.parse 校验，避免误伤正文中的 { }。
 */
function splitContent(content: string): ContentSplit {
  const blocks: string[] = []
  const n = content.length
  let text = ''
  let i = 0
  while (i < n) {
    const ch = content[i]
    if (ch === '{' || ch === '[') {
      const start = i
      let depth = 0
      let inStr = false
      let esc = false
      let closed = false
      for (; i < n; i++) {
        const c = content[i]
        if (inStr) {
          if (esc) esc = false
          else if (c === '\\') esc = true
          else if (c === '"') inStr = false
          continue
        }
        if (c === '"') {
          inStr = true
          continue
        }
        if (c === '{' || c === '[') depth++
        else if (c === '}' || c === ']') {
          depth--
          if (depth === 0) {
            closed = true
            const candidate = content.slice(start, i + 1)
            try {
              JSON.parse(candidate)
              blocks.push(candidate.trim())
              text += '\n'
            } catch {
              text += content.slice(start, i + 1)
            }
            i++
            break
          }
        }
      }
      if (!closed) {
        // 未闭合（正文中的孤立括号），剩余部分直接归正文
        text += content.slice(start)
        break
      }
      continue
    }
    text += ch
    i++
  }
  return { text: text.replace(/\n{3,}/g, '\n\n').trim(), jsonBlocks: blocks }
}

/** 当前消息的内容拆分（仅 AI 消息需要拆分，用户消息原样展示） */
const split = computed<ContentSplit>(() => {
  if (props.message.role !== 1) return { text: props.message.content || '', jsonBlocks: [] }
  return splitContent(props.message.content || '')
})

/** 思考卡片标题：工具调用步数 + JSON 块数 */
const thinkingLabel = computed(() => {
  const parts: string[] = []
  if (props.message.tool_calls?.length) parts.push(`${props.message.tool_calls.length} 步工具调用`)
  if (split.value.jsonBlocks.length) parts.push(`${split.value.jsonBlocks.length} 段过程数据`)
  return parts.length ? `（${parts.join(' · ')}）` : ''
})

/** 是否展示思考卡片：有工具调用或剥离出 JSON 过程数据 */
const showThinking = computed(
  () => props.message.role === 1 && (!!props.message.tool_calls?.length || split.value.jsonBlocks.length > 0),
)
</script>

<template>
  <div class="message-row" :class="message.role === 1 ? 'assistant' : 'user'">
    <div class="avatar" :class="message.role === 1 ? 'ai-avatar' : 'user-avatar'">
      {{ message.role === 1 ? 'AI' : '我' }}
    </div>

    <!-- 思考过程：独立折叠卡片（工具调用 + JSON 过程数据），与最终回复分开单独查看 -->
    <div v-if="showThinking" class="thinking-card">
      <div class="thinking-header" @click="thinkingExpanded = !thinkingExpanded">
        <span class="thinking-icon">💭</span>
        <span class="thinking-title">思考过程{{ thinkingLabel }}</span>
        <span class="thinking-arrow">{{ thinkingExpanded ? '收起' : '展开' }}</span>
      </div>
      <div v-if="thinkingExpanded" class="thinking-body">
        <MsgToolCalls v-if="message.tool_calls?.length" :tool-calls="message.tool_calls" />
        <div
          v-for="(block, bi) in split.jsonBlocks"
          :key="bi"
          class="thinking-json"
          :class="{ 'thinking-json-first': bi === 0 }"
        >
          <pre>{{ block }}</pre>
        </div>
      </div>
    </div>

    <div class="message-bubble" :class="message.role === 1 ? 'assistant' : 'user'">
      <!-- 流式输出中：打字动画 -->
      <template v-if="message.loading">
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
      </template>

      <template v-else>
        <!-- 正文（JSON 过程数据已剥离到上方思考卡片） -->
        <div v-if="split.text" class="message-content">{{ split.text }}</div>

        <!-- 文件上下文：折叠显示，点击展开提取文本 -->
        <div
          v-if="message.file_extracted_text"
          class="file-context"
          @click="fileExpanded = !fileExpanded"
        >
          <div class="file-header">
            <span>📎 {{ message.file_name || '附件' }}</span>
            <span class="file-arrow">{{ fileExpanded ? '收起' : '展开' }}</span>
          </div>
          <pre v-if="fileExpanded" class="file-text">{{ message.file_extracted_text }}</pre>
        </div>

        <!-- 引用来源：折叠显示，点击展开来源列表（知识问答 intent=3） -->
        <div
          v-if="message.sources?.length"
          class="source-context"
          @click="sourceExpanded = !sourceExpanded"
        >
          <div class="source-header">
            <span>📚 引用来源（{{ message.sources.length }}）</span>
            <span class="source-arrow">{{ sourceExpanded ? '收起' : '展开' }}</span>
          </div>
          <div v-if="sourceExpanded" class="source-list">
            <div v-for="(s, i) in message.sources" :key="s.chunk_id ?? i" class="source-item">
              <div class="source-meta">
                <span class="source-file">{{ s.file_name || '未知来源' }}</span>
                <span class="source-score">{{ formatScore(s.score) }}</span>
              </div>
              <div class="source-text">{{ s.text }}</div>
            </div>
          </div>
        </div>
      </template>
    </div>

    <span class="message-time">{{ formatTime(message.created_at) }}</span>
  </div>
</template>

<style scoped>
.message-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.message-row.user {
  flex-direction: row-reverse;
}
.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}
.ai-avatar {
  background: var(--primary);
  color: #fff;
}
.user-avatar {
  background: #f3f4f6;
  color: var(--text-secondary);
}
.message-bubble {
  max-width: 640px;
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.7;
}
.message-bubble.assistant {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
}
.message-bubble.user {
  background: var(--primary);
  color: #fff;
}
.message-content {
  white-space: pre-wrap;
  word-break: break-word;
}
.message-time {
  align-self: center;
  font-size: 12px;
  color: var(--text-muted);
}

/* 思考过程：独立折叠卡片（与气泡对齐，可单独展开查看） */
.thinking-card {
  align-self: flex-start;
  max-width: 640px;
  min-width: 0;
  border: 1px dashed var(--border);
  border-radius: 8px;
  background: #fafbfc;
  overflow: hidden;
  margin-top: 2px;
}
.thinking-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
  color: var(--text-secondary);
}
.thinking-header:hover {
  background: #f3f4f6;
}
.thinking-icon {
  color: var(--text-muted);
}
.thinking-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thinking-arrow {
  font-size: 12px;
  color: var(--text-muted);
  flex-shrink: 0;
}
.thinking-body {
  padding: 8px 12px;
  border-top: 1px dashed var(--border);
}
.thinking-body :deep(.tool-calls) {
  margin-bottom: 0;
}
/* 思考卡片内的 JSON 过程数据块 */
.thinking-json {
  margin-top: 8px;
}
.thinking-json-first {
  margin-top: 0;
}
.thinking-json pre {
  margin: 0;
  padding: 8px 10px;
  background: #f6f7f9;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 240px;
  overflow-y: auto;
  color: var(--text-secondary);
}

/* 文件上下文折叠 */
.file-context {
  margin-top: 8px;
  border-top: 1px dashed var(--border);
  padding-top: 8px;
  cursor: pointer;
}
.file-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--primary);
}
.file-arrow {
  font-size: 12px;
  color: var(--text-muted);
}
.file-text {
  margin: 8px 0 0;
  padding: 8px 10px;
  background: #f6f7f9;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 260px;
  overflow-y: auto;
  color: var(--text-secondary);
}

/* 引用来源折叠 */
.source-context {
  margin-top: 8px;
  border-top: 1px dashed var(--border);
  padding-top: 8px;
  cursor: pointer;
}
.source-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--primary);
}
.source-arrow {
  font-size: 12px;
  color: var(--text-muted);
}
.source-list {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.source-item {
  padding: 8px 10px;
  background: #f6f7f9;
  border-radius: 6px;
  font-size: 12px;
  cursor: default;
}
.source-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.source-file {
  color: var(--primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-score {
  color: var(--text-muted);
  flex-shrink: 0;
}
.source-text {
  color: var(--text-secondary);
  line-height: 1.6;
  word-break: break-all;
}

/* 打字动画 */
.typing-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-muted);
  margin-right: 4px;
  animation: typing 1.2s infinite;
}
.typing-dot:nth-child(2) {
  animation-delay: 0.2s;
}
.typing-dot:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes typing {
  0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-3px); }
}
</style>
