import { ref, computed } from 'vue'

export type Role = 'business' | 'tech'

// 角色持久化：登录选择后写入 localStorage，刷新页面保持一致
const saved = (localStorage.getItem('user_role') as Role) || 'business'
const role = ref<Role>(saved)

export function useRole() {
  const isBusiness = computed(() => role.value === 'business')

  function setRole(r: Role) {
    role.value = r
    localStorage.setItem('user_role', r)
  }

  function toggleRole() {
    setRole(role.value === 'business' ? 'tech' : 'business')
  }

  return { role, isBusiness, setRole, toggleRole }
}
