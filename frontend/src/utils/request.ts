/**
 * axios 二次封装：
 * 1. 请求拦截器：自动携带 Bearer Token
 * 2. 响应拦截器：
 *    - 401 时自动用 refresh_token 刷新并重试原请求
 *    - 其他错误统一提示（可配置是否静默）
 * 3. 刷新失败或 403 时清理 token 并跳转登录页
 */

import axios, { type AxiosError, type AxiosRequestConfig, type AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

export const BASE_URL = 'http://127.0.0.1:8000'

const service = axios.create({
  baseURL: BASE_URL,
  timeout: 10000,
})

// 是否正在刷新中（防止并发刷新）
let isRefreshing = false
// 刷新期间挂起的请求队列
let pendingQueue: Array<(token: string) => void> = []

// 请求拦截器：自动带 token
service.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// 响应拦截器：处理 401 刷新重试 + 全局错误提示
service.interceptors.response.use(
  (response: AxiosResponse) => {
    // 业务错误码非 0 时统一提示
    const { code, message } = response.data
    if (code !== undefined && code !== 0) {
      ElMessage.error(message || '请求失败')
      return Promise.reject(new Error(message || '请求失败'))
    }
    return response
  },
  async (error: AxiosError) => {
    const originalRequest = error.config as AxiosRequestConfig & { _retry?: boolean }

    // 401 且未重试过 → 尝试刷新
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // 刷新中，挂起请求等刷新完成后重试
        return new Promise((resolve) => {
          pendingQueue.push((token: string) => {
            if (originalRequest.headers) {
              originalRequest.headers.Authorization = `Bearer ${token}`
            }
            resolve(service(originalRequest))
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      const refreshToken = localStorage.getItem('refresh_token')
      if (!refreshToken) {
        // 无 refresh_token，直接跳登录
        clearAuthAndRedirect()
        return Promise.reject(error)
      }

      try {
        // 调用刷新接口
        const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {
          refresh_token: refreshToken,
        })
        const newToken = data.data.access_token

        // 更新本地 token
        localStorage.setItem('access_token', newToken)

        // 重试挂起的请求
        pendingQueue.forEach((cb) => cb(newToken))
        pendingQueue = []

        // 重试原请求
        if (originalRequest.headers) {
          originalRequest.headers.Authorization = `Bearer ${newToken}`
        }
        return service(originalRequest)
      } catch (refreshError) {
        // 刷新失败，清理并跳登录
        clearAuthAndRedirect()
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    // 其他错误提示
    const data = error.response?.data as { message?: string } | undefined
    const msg = data?.message || error.message || '网络错误'
    ElMessage.error(msg)
    return Promise.reject(error)
  },
)

/** 清理认证信息并跳转登录页 */
function clearAuthAndRedirect() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('user_info')
  router.push({ name: 'Login' })
  ElMessage.warning('登录已过期，请重新登录')
}

export default service
