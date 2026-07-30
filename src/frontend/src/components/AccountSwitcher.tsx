/**
 * 账号切换。
 *
 * 多角色运营系统的常规能力：同一人可能持有多个工号（运营 / 核销 / 管理），
 * 无需退出再登录。演示时也正好用它在角色间快速切换。
 */

import { Avatar, List, Modal, Tag, Typography, App as AntApp } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { DEFAULT_ROUTE, useAuth } from '../auth/AuthContext'
import { ROLE_LABEL } from '../api/types'
import type { Role } from '../api/types'

const ACCOUNTS: { username: string; name: string; role: Role; dept: string }[] = [
  { username: 'op001', name: '李彦', role: 'OPERATOR', dept: '市场营销部' },
  { username: 'verifier001', name: '王磊', role: 'VERIFIER', dept: '门店运营部' },
  { username: 'admin001', name: '张岚', role: 'ADMIN', dept: '数据与风控部' },
  { username: 'user_a', name: '陈嘉', role: 'USER', dept: '会员' },
  { username: 'user_b', name: '周宁', role: 'USER', dept: '会员' },
  { username: 'user_c', name: '孙涛', role: 'USER', dept: '会员' },
]

const ROLE_COLOR: Record<Role, string> = {
  OPERATOR: 'blue',
  VERIFIER: 'cyan',
  ADMIN: 'purple',
  USER: 'default',
}

export function AccountSwitcher({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [busy, setBusy] = useState<string | null>(null)

  const pick = async (username: string) => {
    if (username === user?.username) {
      onClose()
      return
    }
    setBusy(username)
    try {
      const next = await login(username)
      message.success(`已切换至 ${next.display_name}`)
      onClose()
      navigate(DEFAULT_ROUTE[next.role], { replace: true })
    } catch {
      message.error('切换失败，请重试')
    } finally {
      setBusy(null)
    }
  }

  return (
    <Modal open={open} onCancel={onClose} footer={null} title="切换账号" width={460}>
      <List
        dataSource={ACCOUNTS}
        renderItem={(a) => (
          <List.Item
            style={{
              cursor: 'pointer',
              padding: '10px 8px',
              borderRadius: 4,
              background: a.username === user?.username ? '#f0f5ff' : undefined,
              opacity: busy && busy !== a.username ? 0.5 : 1,
            }}
            onClick={() => pick(a.username)}
          >
            <List.Item.Meta
              avatar={
                <Avatar style={{ background: '#1b4b91', verticalAlign: 'middle' }}>
                  {a.name.slice(0, 1)}
                </Avatar>
              }
              title={
                <span>
                  {a.name}
                  <Tag color={ROLE_COLOR[a.role]} style={{ marginLeft: 8 }}>
                    {ROLE_LABEL[a.role]}
                  </Tag>
                  {a.username === user?.username && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      当前
                    </Typography.Text>
                  )}
                </span>
              }
              description={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {a.dept} · {a.username}
                </Typography.Text>
              }
            />
          </List.Item>
        )}
      />
    </Modal>
  )
}
