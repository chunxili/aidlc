/**
 * 角色路由守卫。
 *
 * **守卫是体验层，不是安全层。** 真正的授权在后端（FR-061）：
 * 前端隐藏入口不构成保护。演示时需说明这一点，否则"四个角色"
 * 会被理解为四个前端页面。
 */

import { Result, Spin } from 'antd'
import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import type { Role } from '../api/types'
import { useAuth } from './AuthContext'

export function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div style={{ padding: 80, textAlign: 'center' }}>
        <Spin size="large" tip="加载中…" />
      </div>
    )
  }
  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }
  if (!roles.includes(user.role)) {
    return (
      <Result
        status="403"
        title="403"
        subTitle="当前角色无权访问该页面。后端同样会拒绝越权请求。"
      />
    )
  }
  return <>{children}</>
}
