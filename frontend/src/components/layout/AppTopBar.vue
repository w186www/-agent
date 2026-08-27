<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import { useRole } from '@/stores/role'
import { useAuth } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const { role, setRole } = useRole()
const { userInfo, clearAuth } = useAuth()

function handleRoleChange(newRole: 'business' | 'tech') {
  setRole(newRole)
  
  // 如果当前页面不在新角色的导航中，跳转到对话助手
  const currentPath = route.path
  const businessPaths = ['/chat']
  const techPaths = ['/chat', '/assessment', '/review']
  
  const allowedPaths = newRole === 'business' ? businessPaths : techPaths
  
  if (!allowedPaths.includes(currentPath)) {
    router.push('/chat')
  }
}

function handleLogout() {
  clearAuth()
  router.push({ name: 'Login' })
}
</script>

<template>
  <header class="topbar">
    <div class="topbar-left">
      <span class="topbar-dot"></span>
      <span class="topbar-title">等保测评助手</span>
    </div>
    <div class="topbar-right">
      <div class="role-switch">
        <button
          class="role-btn"
          :class="{ active: role === 'business' }"
          @click="handleRoleChange('business')"
        >
          商务
        </button>
        <button
          class="role-btn"
          :class="{ active: role === 'tech' }"
          @click="handleRoleChange('tech')"
        >
          技术
        </button>
      </div>
      <div class="user-info">
        <span class="username">{{ userInfo?.username || '用户' }}</span>
        <button class="logout-btn" @click="handleLogout">退出</button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 52px;
  padding: 0 20px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.topbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.topbar-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--primary);
}
.topbar-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}
.role-switch {
  display: flex;
  background: #f3f4f6;
  border-radius: 20px;
  padding: 3px;
}
.role-btn {
  border: none;
  background: transparent;
  padding: 5px 18px;
  border-radius: 18px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}
.role-btn.active {
  background: var(--primary);
  color: #fff;
  box-shadow: var(--shadow-sm);
}

.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: 16px;
}
.username {
  font-size: 13px;
  color: var(--text-secondary);
}
.logout-btn {
  border: none;
  background: transparent;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: all 0.2s;
}
.logout-btn:hover {
  background: #f3f4f6;
  color: var(--danger);
}
</style>
