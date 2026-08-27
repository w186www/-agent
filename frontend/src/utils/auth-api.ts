/**
 * 认证相关 API：登录 / 注册 / 刷新令牌
 */

import request from './request'

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  password: string
}

export interface RefreshRequest {
  refresh_token: string
}

export interface LoginResponse {
  code: number
  message: string
  data: {
    access_token: string
    refresh_token: string
    token_type: string
    expires_in: number
    user: {
      id: number
      username: string
    }
  }
}

export interface RegisterResponse {
  code: number
  message: string
  data: {
    id: number
    username: string
  }
}

export interface RefreshResponse {
  code: number
  message: string
  data: {
    access_token: string
    refresh_token: string
    token_type: string
    expires_in: number
  }
}

/** 登录 */
export function loginApi(data: LoginRequest) {
  return request.post<LoginResponse>('/auth/login', data)
}

/** 注册 */
export function registerApi(data: RegisterRequest) {
  return request.post<RegisterResponse>('/auth/register', data)
}

/** 刷新令牌 */
export function refreshApi(data: RefreshRequest) {
  return request.post<RefreshResponse>('/auth/refresh', data)
}
