// ============================================
// 登录态本地存储
// Token 与用户信息持久化到 localStorage，
// api.ts 与页面模块统一从这里读写，避免循环依赖。
// ============================================

export interface AuthUser {
  user_id: string
  username: string
  nickname: string | null
}

const TOKEN_KEY = 'shapeai_token'
const USER_KEY = 'shapeai_user'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getAuthUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export function setAuth(token: string, user: AuthUser): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function isLoggedIn(): boolean {
  return !!getToken()
}

/** 当前业务用户 ID（= 用户名），所有数据接口按此隔离 */
export function getCurrentUserId(): string {
  return getAuthUser()?.user_id || 'anonymous'
}

/** 登录过期/未登录时跳转登录页（避免重复跳转） */
export function redirectToLogin(): void {
  if (!window.location.pathname.startsWith('/login')) {
    window.location.href = '/login'
  }
}
