<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Conversation } from '@/types/chat'
import { INTENT_TYPES } from '@/types/chat'
import { createSessionApi, deleteSessionApi, getSessionsApi, updateSessionApi } from '@/utils/chat-api'

const props = defineProps<{
  /** 会话角色类型筛选：0=商务，1=技术 */
  roleType: number
  /** 当前选中会话 ID */
  activeId: number | null
  /** 新建会话可选意图（按角色过滤；缺省=全部） */
  intentTypes?: number[]
}>()

const emit = defineEmits<{
  (e: 'select', conversation: Conversation | null): void
  (e: 'created', conversation: Conversation): void
}>()

/** 新建会话弹窗可选意图（按角色过滤） */
const intentOptions = computed(() => {
  const allowed = props.intentTypes
  return allowed ? INTENT_TYPES.filter((t) => allowed.includes(t.value)) : [...INTENT_TYPES]
})

// ── 会话列表分页状态 ──
const sessions = ref<Conversation[]>([])
const page = ref(1)
const total = ref(0)
const loading = ref(false)
const loadingMore = ref(false)
const hasMore = ref(true)

// ── 新建会话弹窗 ──
const showCreate = ref(false)
const createIntent = ref<number>(0)
const createTitle = ref('')
const creating = ref(false)

// ── 重命名 ──
const renamingId = ref<number | null>(null)
const renameTitle = ref('')

// ── 意图筛选 tabs（全部 / 各会话类型）──
const filterIntent = ref<number | null>(null)

function setFilter(v: number | null) {
  if (filterIntent.value === v) return
  filterIntent.value = v
  loadFirstPage()
}

const PAGE_SIZE = 20

/** 加载第一页（切换角色筛选或刷新时调用） */
async function loadFirstPage() {
  loading.value = true
  try {
    const res = await getSessionsApi({
      page: 1,
      page_size: PAGE_SIZE,
      role_type: props.roleType,
      intent_type: filterIntent.value ?? undefined,
    })
    sessions.value = res.data.data.items
    total.value = res.data.data.total
    page.value = 1
    hasMore.value = sessions.value.length < total.value
  } finally {
    loading.value = false
  }
}

/** 滚动到底部加载下一页（会话列表向下翻页） */
async function loadMore() {
  if (loadingMore.value || !hasMore.value || loading.value) return
  loadingMore.value = true
  try {
    const next = page.value + 1
    const res = await getSessionsApi({
      page: next,
      page_size: PAGE_SIZE,
      role_type: props.roleType,
      intent_type: filterIntent.value ?? undefined,
    })
    const items = res.data.data.items
    sessions.value = [...sessions.value, ...items]
    total.value = res.data.data.total
    page.value = next
    hasMore.value = items.length > 0 && sessions.value.length < total.value
  } finally {
    loadingMore.value = false
  }
}

function handleScroll(e: Event) {
  const el = e.target as HTMLElement
  // 距底部 40px 内触发加载
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 40) {
    loadMore()
  }
}

function selectConversation(conv: Conversation) {
  emit('select', conv)
}

// ── 新建会话 ──
/** 打开新建会话弹窗（意图重置为角色允许的第一个） */
function openCreate() {
  createIntent.value = intentOptions.value[0]?.value ?? 0
  showCreate.value = true
}

async function handleCreate() {
  if (creating.value) return
  creating.value = true
  try {
    const res = await createSessionApi({
      role_type: props.roleType,
      intent_type: createIntent.value,
      title: createTitle.value.trim() || undefined,
    })
    const conv = res.data.data
    showCreate.value = false
    createTitle.value = ''
    ElMessage.success('会话创建成功')
    // 刷新列表并选中新会话
    await loadFirstPage()
    emit('created', conv)
  } finally {
    creating.value = false
  }
}

// ── 重命名 ──
function startRename(conv: Conversation) {
  renamingId.value = conv.id
  renameTitle.value = conv.title
}

async function confirmRename() {
  if (renamingId.value === null || !renameTitle.value.trim()) return
  try {
    const res = await updateSessionApi(renamingId.value, { title: renameTitle.value.trim() })
    const idx = sessions.value.findIndex((s) => s.id === res.data.data.id)
    if (idx !== -1) sessions.value[idx] = res.data.data
    ElMessage.success('标题已更新')
  } finally {
    renamingId.value = null
  }
}

// ── 删除会话 ──
async function handleDelete(conv: Conversation) {
  try {
    await ElMessageBox.confirm(`确定删除会话「${conv.title}」？会话内消息将一并删除。`, '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  await deleteSessionApi(conv.id)
  ElMessage.success('会话已删除')
  await loadFirstPage()
  // 删除的是当前会话时，通知上层切换（无剩余会话则传 null 清空消息区）
  if (props.activeId === conv.id) {
    emit('select', sessions.value[0] ?? null)
  }
}

// 角色切换时重新加载会话列表
watch(() => props.roleType, loadFirstPage)

onMounted(loadFirstPage)
</script>

<template>
  <div class="chat-sidebar">
    <div class="sidebar-header">
      <span class="sidebar-title">会话列表</span>
      <el-button type="primary" size="small" circle @click="openCreate">
        <el-icon><Plus /></el-icon>
      </el-button>
    </div>

    <div class="intent-tabs">
      <span
        class="intent-tab"
        :class="{ active: filterIntent === null }"
        @click="setFilter(null)"
      >全部</span>
      <span
        v-for="t in intentOptions"
        :key="t.value"
        class="intent-tab"
        :class="{ active: filterIntent === t.value }"
        @click="setFilter(t.value)"
      >{{ t.label }}</span>
    </div>

    <div
      class="conversation-list"
      v-loading="loading"
      @scroll="handleScroll"
    >
      <div
        v-for="conv in sessions"
        :key="conv.id"
        class="conversation-item"
        :class="{ active: conv.id === activeId }"
        @click="selectConversation(conv)"
      >
        <div class="conv-main">
          <div class="conv-title">{{ conv.title }}</div>
          <div class="conv-subtitle">
            {{ INTENT_TYPES.find((t) => t.value === conv.intent_type)?.label || '对话' }}
          </div>
        </div>
        <div class="conv-actions" @click.stop>
          <el-tooltip content="重命名" placement="top">
            <el-icon class="action-icon" @click="startRename(conv)"><EditPen /></el-icon>
          </el-tooltip>
          <el-tooltip content="删除" placement="top">
            <el-icon class="action-icon danger" @click="handleDelete(conv)"><Delete /></el-icon>
          </el-tooltip>
        </div>

        <!-- 行内重命名输入框 -->
        <div v-if="renamingId === conv.id" class="rename-box" @click.stop>
          <el-input
            v-model="renameTitle"
            size="small"
            autofocus
            @keydown.enter="confirmRename"
            @blur="confirmRename"
          />
        </div>
      </div>

      <div v-if="!sessions.length && !loading" class="empty-tip">暂无会话，点击右上角新建</div>
      <div v-if="loadingMore" class="load-tip">加载中…</div>
    </div>

    <!-- 新建会话弹窗 -->
    <el-dialog v-model="showCreate" title="新建会话" width="420px">
      <div class="form-field">
        <label class="field-label">会话类型</label>
        <el-select v-model="createIntent" style="width: 100%">
          <el-option
            v-for="t in intentOptions"
            :key="t.value"
            :label="t.label"
            :value="t.value"
          />
        </el-select>
      </div>
      <div class="form-field">
        <label class="field-label">标题（可选，留空自动生成）</label>
        <el-input v-model="createTitle" placeholder="请输入会话标题" maxlength="50" />
      </div>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.chat-sidebar {
  width: 260px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
}
.sidebar-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.intent-tabs {
  display: flex;
  gap: 4px;
  padding: 0 12px 8px;
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
}
.intent-tab {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-muted);
  padding: 3px 10px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.intent-tab:hover {
  color: var(--primary);
  background: var(--primary-light);
}
.intent-tab.active {
  color: var(--primary);
  background: var(--primary-light);
  font-weight: 600;
}
.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}
.conversation-item {
  position: relative;
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 4px;
  cursor: pointer;
  transition: all 0.15s;
}
.conversation-item:hover {
  background: #f9fafb;
}
.conversation-item.active {
  background: var(--primary-light);
}
.conv-main {
  min-width: 0;
}
.conv-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-subtitle {
  font-size: 12px;
  color: var(--text-muted);
}
.conv-actions {
  position: absolute;
  top: 10px;
  right: 8px;
  display: none;
  gap: 6px;
  background: var(--surface);
  padding: 2px 4px;
  border-radius: 6px;
}
.conversation-item:hover .conv-actions {
  display: flex;
}
.action-icon {
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 14px;
}
.action-icon:hover {
  color: var(--primary);
}
.action-icon.danger:hover {
  color: var(--danger);
}
.rename-box {
  margin-top: 8px;
}
.empty-tip,
.load-tip {
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
  padding: 16px 0;
}
.form-field {
  margin-bottom: 16px;
}
.field-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 6px;
}
</style>
