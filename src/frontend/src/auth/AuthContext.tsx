/**
 * 登录态。唯一的全局状态，因此用 Context 而非 Redux/Zustand
 * （frontend-design.md 第四节）。
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, setUnauthenticatedHandler, tokenStore } from '../api/client'
import type { LoginResult, Role, User } from '../api/types'

interface AuthState {
  user: User | null
  loading: boolean
  login: (username: string) => Promise<User>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

/** 各角色登录后的默认落地页（frontend-design.md 第一节） */
export const DEFAULT_ROUTE: Record<Role, string> = {
  USER: '/coupons',
  VERIFIER: '/verify',
  OPERATOR: '/campaigns',
  ADMIN: '/stats',
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  // 刷新后用 /api/auth/me 恢复登录态
  useEffect(() => {
    setUnauthenticatedHandler(() => setUser(null))
    if (!tokenStore.get()) {
      setLoading(false)
      return
    }
    api
      .get<User>('/api/auth/me')
      .then(setUser)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (username: string) => {
    const result = await api.post<LoginResult>('/api/auth/login', { username })
    tokenStore.set(result.access_token)
    setUser(result.user)
    return result.user
  }, [])

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return ctx
}
