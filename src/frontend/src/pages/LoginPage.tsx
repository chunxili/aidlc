/** 登录页。Mock 用户，不做注册（FR-060、需求 4.7）。 */

import { Alert, Button, Card, Divider, Form, Input, Space, Typography, message } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { DEFAULT_ROUTE, useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'

// 竞赛演示流程用到的账号（FR-062 seed）
const DEMO_ACCOUNTS = [
  { username: 'op001', label: '运营小李（创建活动 / 审核风险标记）' },
  { username: 'user_a', label: '用户A（演示步骤 b、d）' },
  { username: 'user_b', label: '用户B（演示步骤 c 库存不足）' },
  { username: 'user_c', label: '用户C（演示步骤 f 高频风控）' },
  { username: 'verifier001', label: '核销员小王（演示步骤 d、e）' },
  { username: 'admin001', label: '管理员小张（统计与异常监控）' },
]

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)

  const doLogin = async (username: string) => {
    setLoading(true)
    try {
      const user = await login(username)
      message.success(`已登录：${user.display_name}`)
      navigate(DEFAULT_ROUTE[user.role], { replace: true })
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 64 }}>
      <Card title="优惠券发放与核销中心" style={{ width: 520 }}>
        <Alert
          type="info"
          showIcon
          message="Mock 登录"
          description="演示项目不做注册与密码体系，输入用户名即可登录（需求 4.7）。"
          style={{ marginBottom: 16 }}
        />
        <Form layout="inline" onFinish={(v) => doLogin(v.username)} style={{ marginBottom: 8 }}>
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]} style={{ flex: 1 }}>
            <Input placeholder="用户名，例如 user_a" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading}>
              登录
            </Button>
          </Form.Item>
        </Form>

        <Divider plain>演示账号</Divider>
        <Space direction="vertical" style={{ width: '100%' }}>
          {DEMO_ACCOUNTS.map((a) => (
            <Button key={a.username} block onClick={() => doLogin(a.username)} loading={loading}>
              <Typography.Text code>{a.username}</Typography.Text>
              <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                {a.label}
              </Typography.Text>
            </Button>
          ))}
        </Space>
        <Typography.Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0 }}>
          并发验收另有 user001 ~ user200 共 200 个批量账号（FR-010 AC-1 需要 N+1 个不同用户）。
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
