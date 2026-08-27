<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppTopBar from '@/components/layout/AppTopBar.vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'

const route = useRoute()

// 登录页独立全屏渲染，不走布局框架
const isLoginPage = computed(() => route.name === 'Login')
</script>

<template>
  <!-- 登录页：直接渲染，无顶栏/侧栏 -->
  <router-view v-if="isLoginPage" />

  <!-- 工作台：完整布局 -->
  <div v-else class="app">
    <AppTopBar />
    <div class="body">
      <AppSidebar />
      <main class="main-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* ── 主体三栏 ── */
.body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ── 中间主内容 ── */
.main-content {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
</style>
