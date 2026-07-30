/**
 * 角色路由守卫。
 *
 * 仅控制界面可达性；接口权限由后端独立校验，前端不承担安全职责。
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
      <div style={{ padding: 96, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }
  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }
  if (!roles.includes(user.role)) {
    return <Result status="403" title="无访问权限" subTitle="当前账号无权查看该页面" />
  }
  return <>{children}</>
}
