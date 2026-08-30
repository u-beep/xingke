// ============================================
// 认证 API 服务
// 注册 / 登录 / 当前用户 / 退出
// ============================================

import { request } from './api'
import type { AuthUser } from './authStore'

interface AuthResponse {
  token: string
  user: AuthUser
}

export const authApi = {
  /** 注册新用户（成功即自动登录，返回 token） */
  async register(data: { username: string; password: string; nickname?: string }): Promise<AuthResponse> {
    return request<AuthResponse>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 登录 */
  async login(data: { username: string; password: string }): Promise<AuthResponse> {
    return request<AuthResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 获取当前登录用户信息 */
  async me(): Promise<{ user: AuthUser }> {
    return request<{ user: AuthUser }>('/api/v1/auth/me')
  },

  /** 退出登录（吊销服务端 Token） */
  async logout(): Promise<{ success: boolean }> {
    return request<{ success: boolean }>('/api/v1/auth/logout', { method: 'POST' })
  },
}
