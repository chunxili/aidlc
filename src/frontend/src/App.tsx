/** 应用外壳：侧边导航 + 顶栏 + 内容区。 */

import { Avatar, Badge, Dropdown, Layout, Menu, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { api } from './api/client'
import { DEFAULT_ROUTE, useAuth } from './auth/AuthContext'
import { RequireRole } from './auth/RequireRole'
import { AccountSwitcher } from './components/AccountSwitcher'
import { ROLE_LABEL } from './api/types'
import type { Overview, Role } from './api/types'
import { BRAND } from './theme'
import LoginPage from './pages/LoginPage'
import CouponsPage from './pages/CouponsPage'
import MyCouponsPage from './pages/MyCouponsPage'
import VerifyPage from './pages/VerifyPage'
import CampaignsPage from './pages/CampaignsPage'
import RiskPage from './pages/RiskPage'
import StatsPage from './pages/StatsPage'

interface NavItem {
  key: string
  label: string
  roles: Role[]
  group: string
  badge?: 'riskPending'
}

const NAV: NavItem[] = [
  { key: '/coupons', label: '领券中心', roles: ['USER'], group: '会员' },
  { key: '/my-coupons', label: '我的优惠券', roles: ['USER'], group: '会员' },
  { key: '/campaigns', label: '活动管理', roles: ['OPERATOR'], group: '营销' },
  { key: '/risk', label: '风险名单', roles: ['OPERATOR'], group: '营销', badge: 'riskPending' },
  { key: '/verify', label: '券码核销', roles: ['VERIFIER'], group: '门店' },
  { key: '/stats', label: '数据看板', roles: ['ADMIN', 'OPERATOR'], group: '数据' },
]

export default function App() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const [switcherOpen, setSwitcherOpen] = useState(false)
  const [riskPending, setRiskPending] = useState(0)

  // 侧边栏的待处理角标：运营与管理员才有权读取该计数
  const refreshBadge = useCallback(async () => {
    if (!user || (user.role !== 'OPERATOR' && user.role !== 'ADMIN')) {
      setRiskPending(0)
      return
    }
    try {
      if (user.role === 'ADMIN') {
        const o = await api.get<Overview>('/api/stats/overview')
        setRiskPending(o.risk_pending_count)
      } else {
        const r = await api.get<{ total: number }>('/api/risk/events?status=PENDING&page_size=1')
        setRiskPending(r.total)
      }
    } catch {
      setRiskPending(0)
    }
  }, [user])

  useEffect(() => {
    void refreshBadge()
    const t = setInterval(refreshBadge, 15000)
    return () => clearInterval(t)
  }, [refreshBadge, location.pathname])

  if (location.pathname === '/login') {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
      </Routes>
    )
  }

  const visible = NAV.filter((n) => user && n.roles.includes(user.role))
  const groups = [...new Set(visible.map((n) => n.group))]
  const menuItems = groups.map((g) => ({
    key: g,
    type: 'group' as const,
    label: g,
    children: visible
      .filter((n) => n.group === g)
      .map((n) => ({
        key: n.key,
        label:
          n.badge === 'riskPending' && riskPending > 0 ? (
            <span style={{ display: 'flex', justifyContent: 'space-between', paddingRight: 4 }}>
              {n.label}
              <Badge count={riskPending} size="small" />
            </span>
          ) : (
            n.label
          ),
      })),
  }))

  const current = visible.find((n) => n.key === location.pathname)

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        width={216}
        theme="dark"
      >
        <div className="brand">
          <span className="brand__mark">惠</span>
          {!collapsed && <span className="brand__text">{BRAND.suffix}</span>}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Layout.Sider>

      <Layout>
        <Layout.Header
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            padding: '0 24px',
            borderBottom: '1px solid #e8ebf0',
          }}
        >
          <Typography.Text style={{ flex: 1, fontSize: 14, color: '#6b7488' }}>
            {current ? `${current.group} / ${current.label}` : ''}
          </Typography.Text>
          {user && (
            <Dropdown
              trigger={['click']}
              menu={{
                items: [
                  { key: 'switch', label: '切换账号' },
                  { type: 'divider' },
                  { key: 'logout', label: '退出登录' },
                ],
                onClick: ({ key }) => {
                  if (key === 'switch') setSwitcherOpen(true)
                  if (key === 'logout') {
                    logout()
                    navigate('/login')
                  }
                },
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
                <Avatar size={30} style={{ background: '#1b4b91' }}>
                  {user.display_name.slice(0, 1)}
                </Avatar>
                <div style={{ lineHeight: 1.25 }}>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>{user.display_name}</div>
                  <div style={{ fontSize: 12, color: '#8b93a5' }}>{ROLE_LABEL[user.role]}</div>
                </div>
              </div>
            </Dropdown>
          )}
        </Layout.Header>

        <Layout.Content style={{ padding: 24 }}>
          <div style={{ maxWidth: 'var(--page-max)', margin: '0 auto' }}>
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
                    <RiskPage onHandled={refreshBadge} />
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
          </div>
        </Layout.Content>
      </Layout>

      <AccountSwitcher open={switcherOpen} onClose={() => setSwitcherOpen(false)} />
    </Layout>
  )
}
