/**
 * 审核进度页。
 *
 * 待审核账号能登录但不能办业务，这一页就是它唯一能到的地方 ——
 * 若干脆不让登录，用户无从得知进度，只会反复注册产生垃圾数据。
 */

import { Button, Card, Descriptions, Result, Space, Typography, App as AntApp } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { landingFor, useAuth } from '../auth/AuthContext'
import { ROLE_LABEL } from '../api/types'
import { BRAND } from '../theme'

export default function PendingPage() {
  const { user, refresh, logout } = useAuth()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [checking, setChecking] = useState(false)

  if (!user) return null

  const recheck = async () => {
    setChecking(true)
    try {
      const next = await refresh()
      if (next && next.status === 'ACTIVE') {
        message.success('审核已通过')
        navigate(landingFor(next), { replace: true })
      } else if (next && next.status === 'REJECTED') {
        message.warning('申请未通过')
      } else {
        message.info('仍在审核中，请稍后再查看')
      }
    } finally {
      setChecking(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f4f6f9',
        padding: 24,
      }}
    >
      <Card style={{ width: 520 }}>
        <div className="brand" style={{ padding: 0, marginBottom: 8 }}>
          <span className="brand__mark">惠</span>
          <span className="brand__text" style={{ color: '#1c2434' }}>
            {BRAND.full}
          </span>
        </div>
        <Result
          status="info"
          title="账号审核中"
          subTitle="管理员将尽快处理你的申请，通过后即可开始使用。"
        />
        <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
          <Descriptions.Item label="账号">{user.username}</Descriptions.Item>
          <Descriptions.Item label="姓名">{user.display_name}</Descriptions.Item>
          <Descriptions.Item label="申请角色">{ROLE_LABEL[user.role]}</Descriptions.Item>
          {user.store_name && (
            <Descriptions.Item label="所属门店">{user.store_name}</Descriptions.Item>
          )}
        </Descriptions>
        <Space>
          <Button type="primary" onClick={recheck} loading={checking}>
            刷新审核状态
          </Button>
          <Button
            onClick={() => {
              logout()
              navigate('/login')
            }}
          >
            退出登录
          </Button>
        </Space>
        <Typography.Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0, fontSize: 12 }}>
          如需修改申请资料，可退出后使用同一账号重新提交。
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
