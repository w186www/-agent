import { createRouter, createWebHistory } from 'vue-router'
import type { Role } from '@/stores/role'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: '登录' },
    },
    {
      path: '/',
      redirect: '/chat',
    },
    {
      path: '/chat',
      name: 'Chat',
      component: () => import('@/views/ChatView.vue'),
      meta: { title: '对话助手', requiresAuth: true, roles: ['business', 'tech'] },
    },
    {
      path: '/assessment',
      name: 'Assessment',
      component: () => import('@/views/AssessmentWorkbench.vue'),
      meta: { title: '测评核查', requiresAuth: true, roles: ['tech'] },
    },
    {
      path: '/review',
      name: 'Review',
      component: () => import('@/views/ReviewView.vue'),
      meta: { title: '审核工作台', requiresAuth: true, roles: ['tech'] },
    },
    {
      path: '/knowledge',
      name: 'Knowledge',
      component: () => import('@/views/KnowledgeView.vue'),
      meta: { title: '知识库', requiresAuth: true, roles: ['business', 'tech'] },
    },
    {
      path: '/topology',
      name: 'Topology',
      component: () => import('@/views/TopologyView.vue'),
      meta: { title: '拓扑图', requiresAuth: true, roles: ['business', 'tech'] },
    },
  ],
})

// 路由守卫：未登录时重定向到登录页；角色不匹配时重定向
router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('access_token')
  const role = (localStorage.getItem('user_role') as Role) || 'business'

  // 未登录拦截
  if (to.meta.requiresAuth && !token) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
    return
  }

  // 已登录访问登录页，跳转首页
  if (to.name === 'Login' && token) {
    next({ name: 'Chat' })
    return
  }

  // 角色权限校验
  const allowedRoles = to.meta.roles as Role[] | undefined
  if (allowedRoles && !allowedRoles.includes(role)) {
    // 角色不匹配，跳转到该角色的默认页
    if (role === 'business') {
      next({ name: 'Chat' })
    } else {
      next({ name: 'Chat' })
    }
    return
  }

  next()
})

export default router
