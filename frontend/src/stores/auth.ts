import { ref, computed } from 'vue'

export interface UserInfo {
  id: number
  username: string
}

// 从 localStorage 恢复登录状态
const token = ref<string | null>(localStorage.getItem('access_token'))
const userInfo = ref<UserInfo | null>(
  localStorage.getItem('user_info')
    ? JSON.parse(localStorage.getItem('user_info')!)
    : null,
)

export function useAuth() {
  const isLoggedIn = computed(() => !!token.value)

  function setAuth(t: string, user: UserInfo, refreshToken?: string) {
    token.value = t
    userInfo.value = user
    localStorage.setItem('access_token', t)
    localStorage.setItem('user_info', JSON.stringify(user))
    if (refreshToken) {
      localStorage.setItem('refresh_token', refreshToken)
    }
  }

  function clearAuth() {
    token.value = null
    userInfo.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user_info')
  }

  return { token, userInfo, isLoggedIn, setAuth, clearAuth }
}
