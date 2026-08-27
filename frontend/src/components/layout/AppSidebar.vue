<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useRole } from '@/stores/role'
import { getReviewsApi } from '@/utils/chat-api'

const route = useRoute()
const router = useRouter()
const { role } = useRole()

interface NavItem {
  key: string
  label: string
  icon: string
  badge?: number
}

// 商务导航项（招投标能力已合并进对话助手，按会话类型在页面内切换）
const businessNav: NavItem[] = [
  { key: 'chat', label: '对话助手', icon: 'ChatDotRound' },
]

// 技术导航项
const techNav: NavItem[] = [
  { key: 'chat', label: '对话助手', icon: 'ChatDotRound' },
  { key: 'assessment', label: '测评核查', icon: 'List' },
  { key: 'review', label: '审核工作台', icon: 'CircleCheck' },
]

/** 待审核任务数量（GET /review?status=0 的 total，仅技术角色拉取） */
const reviewCount = ref(0)

async function loadReviewCount() {
  try {
    const res = await getReviewsApi(0)
    reviewCount.value = res.data.data.total ?? 0
  } catch {
    reviewCount.value = 0
  }
}

watch(
  role,
  (r) => {
    if (r === 'tech') {
      loadReviewCount()
    } else {
      reviewCount.value = 0
    }
  },
  { immediate: true },
)

// 根据角色动态返回导航，审核工作台 badge 展示真实待审核数量（为 0 时不显示）
const navItems = computed(() => {
  const items = role.value === 'business' ? businessNav : techNav
  return items.map((item) =>
    item.key === 'review'
      ? { ...item, badge: reviewCount.value > 0 ? reviewCount.value : undefined }
      : item,
  )
})

function go(key: string) {
  router.push(`/${key}`)
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-section">
      <div class="sidebar-section-title">工作区</div>
      <div
        v-for="item in navItems"
        :key="item.key"
        class="nav-item"
        :class="{ active: route.name === item.key }"
        @click="go(item.key)"
      >
        <el-icon><component :is="item.icon" /></el-icon>
        <span class="nav-label">{{ item.label }}</span>
        <el-badge v-if="item.badge" :value="item.badge" class="nav-badge" />
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 200px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
  padding: 16px 0;
  overflow-y: auto;
}
.sidebar-section {
  margin-bottom: 8px;
}
.sidebar-section-title {
  padding: 0 16px 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 14px;
  transition: all 0.15s;
  border-left: 3px solid transparent;
}
.nav-item:hover {
  background: #f9fafb;
  color: var(--text);
}
.nav-item.active {
  background: var(--primary-light);
  color: var(--primary);
  border-left-color: var(--primary);
  font-weight: 500;
}
.nav-item .el-icon {
  font-size: 16px;
}
.nav-label {
  flex: 1;
}
.nav-badge :deep(.el-badge__content) {
  font-size: 10px;
  height: 16px;
  line-height: 16px;
  min-width: 16px;
}
</style>
