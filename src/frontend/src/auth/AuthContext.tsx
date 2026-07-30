/**
 * 登录态。唯一的全局状态，因此用 Context 而非 Redux/Zustand。
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, setUnauthenticatedHandler, tokenStore } from '../api/client'
import type { LoginResult, Role, User } from '../api/types'

interface AuthState {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<User>
  refresh: () => Promise<User | null>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

/** 各角色登录后的默认落地页 */
export const DEFAULT_ROUTE: Record<Role, string> = {
  USER: '/coupons',
  VERIFIER: '/verify',
  OPERATOR: '/campaigns',
  ADMIN: '/admin/registrations',
}

/** 待审核账号只能进这一页 */
export const PENDING_ROUTE = '/pending'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

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

  const login = useCallback(async (username: string, password: string) => {
    const result = await api.post<LoginResult>('/api/auth/login', { username, password })
    tokenStore.set(result.access_token)
    setUser(result.user)
    return result.user
  }, [])

  const refresh = useCallback(async () => {
    if (!tokenStore.get()) return null
    const next = await api.get<User>('/api/auth/me')
    setUser(next)
    return next
  }, [])

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, refresh, logout }),
    [user, loading, login, refresh, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return ctx
}

export function landingFor(user: User): string {
  return user.status === 'PENDING' ? PENDING_ROUTE : DEFAULT_ROUTE[user.role]
}
