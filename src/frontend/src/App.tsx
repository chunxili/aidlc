/** 应用外壳与路由。7 个页面共享一套布局（frontend-design.md 第一节）。 */

import { Button, Layout, Menu, Space, Tag, Typography } from 'antd'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { DEFAULT_ROUTE, useAuth } from './auth/AuthContext'
import { RequireRole } from './auth/RequireRole'
import { ROLE_LABEL } from './api/types'
import type { Role } from './api/types'
import LoginPage from './pages/LoginPage'
import CouponsPage from './pages/CouponsPage'
import MyCouponsPage from './pages/MyCouponsPage'
import VerifyPage from './pages/VerifyPage'
import CampaignsPage from './pages/CampaignsPage'
import RiskPage from './pages/RiskPage'
import StatsPage from './pages/StatsPage'

const NAV: { key: string; label: string; roles: Role[] }[] = [
  { key: '/coupons', label: '领券广场', roles: ['USER'] },
  { key: '/my-coupons', label: '我的券', roles: ['USER'] },
  { key: '/verify', label: '核销台', roles: ['VERIFIER'] },
  { key: '/campaigns', label: '活动管理', roles: ['OPERATOR'] },
  { key: '/risk', label: '风险标记审核', roles: ['OPERATOR'] },
  { key: '/stats', label: '统计面板', roles: ['ADMIN', 'OPERATOR'] },
]

export default function App() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  if (location.pathname === '/login') {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
      </Routes>
    )
  }

  const items = NAV.filter((n) => user && n.roles.includes(user.role)).map((n) => ({
    key: n.key,
    label: n.label,
  }))

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        <Typography.Text strong style={{ color: '#fff', fontSize: 16, whiteSpace: 'nowrap' }}>
          优惠券发放与核销中心
        </Typography.Text>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[location.pathname]}
          items={items}
          onClick={({ key }) => navigate(key)}
          style={{ flex: 1, minWidth: 0 }}
        />
        {user && (
          <Space>
            <Tag color="blue">{ROLE_LABEL[user.role]}</Tag>
            <Typography.Text style={{ color: '#fff' }}>{user.display_name}</Typography.Text>
            <Button
              size="small"
              onClick={() => {
                logout()
                navigate('/login')
              }}
            >
              退出
            </Button>
          </Space>
        )}
      </Layout.Header>

      <Layout.Content style={{ padding: 24, maxWidth: 1280, margin: '0 auto', width: '100%' }}>
        <Routes>
          <Route
            path="/"
            element={<Navigate to={user ? DEFAULT_ROUTE[user.role] : '/login'} replace />}
          />
          <Route
            path="/coupons"
            element={
              <RequireRole roles={['USER']}>
                <CouponsPage />
              </RequireRole>
            }
          />
          <Route
            path="/my-coupons"
            element={
              <RequireRole roles={['USER']}>
                <MyCouponsPage />
              </RequireRole>
            }
          />
          <Route
            path="/verify"
            element={
              <RequireRole roles={['VERIFIER']}>
                <VerifyPage />
              </RequireRole>
            }
          />
          <Route
            path="/campaigns"
            element={
              <RequireRole roles={['OPERATOR']}>
                <CampaignsPage />
              </RequireRole>
            }
          />
          <Route
            path="/risk"
            element={
              <RequireRole roles={['OPERATOR']}>
                <RiskPage />
              </RequireRole>
            }
          />
          <Route
            path="/stats"
            element={
              <RequireRole roles={['ADMIN', 'OPERATOR']}>
                <StatsPage />
              </RequireRole>
            }
          />
        </Routes>
      </Layout.Content>
    </Layout>
  )
}
