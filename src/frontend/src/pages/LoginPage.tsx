import { Button, Checkbox, Form, Input, Typography, App as AntApp } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { DEFAULT_ROUTE, useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'
import { BRAND } from '../theme'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [loading, setLoading] = useState(false)

  const submit = async (values: { username: string }) => {
    setLoading(true)
    try {
      const user = await login(values.username.trim())
      navigate(DEFAULT_ROUTE[user.role], { replace: true })
    } catch (e) {
      message.error(e instanceof ApiError && e.status === 401 ? '账号或密码有误' : '登录失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth">
      <aside className="auth__aside">
        <div className="brand" style={{ padding: 0 }}>
          <span className="brand__mark">惠</span>
          <span className="brand__text">{BRAND.full}</span>
        </div>

        <div>
          <div className="auth__headline">优惠券全生命周期管理，从投放到核销</div>
          <div className="auth__sub">
            活动创建、库存管控、券码核销、风险识别与效果分析，统一在一个平台完成。
          </div>
          <div className="auth__metrics">
            <div>
              <div className="auth__metric-value">99.99%</div>
              <div className="auth__metric-label">库存准确率</div>
            </div>
            <div>
              <div className="auth__metric-value">&lt;100ms</div>
              <div className="auth__metric-label">核销响应</div>
            </div>
            <div>
              <div className="auth__metric-value">7×24</div>
              <div className="auth__metric-label">风控值守</div>
            </div>
          </div>
        </div>

        <div className="auth__foot">© 2026 惠码 · 优惠券中心</div>
      </aside>

      <main className="auth__panel">
        <div className="auth__form">
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            登录
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 28 }}>
            请使用企业账号登录，会员请使用会员编号
          </Typography.Paragraph>

          <Form layout="vertical" onFinish={submit} requiredMark={false} size="large">
            <Form.Item
              name="username"
              label="账号"
              rules={[{ required: true, message: '请输入账号' }]}
            >
              <Input placeholder="请输入账号" autoComplete="username" autoFocus />
            </Form.Item>
            <Form.Item name="password" label="密码">
              <Input.Password placeholder="请输入密码" autoComplete="current-password" />
            </Form.Item>
            <Form.Item style={{ marginBottom: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Checkbox defaultChecked>记住账号</Checkbox>
                <Typography.Link disabled style={{ fontSize: 13 }}>
                  忘记密码
                </Typography.Link>
              </div>
            </Form.Item>
            <Form.Item style={{ marginBottom: 12 }}>
              <Button type="primary" htmlType="submit" block loading={loading}>
                登录
              </Button>
            </Form.Item>
          </Form>

          {/* 不制造"已校验密码"的错觉：当前环境确实不校验，如实告知 */}
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            当前为内测环境，密码校验尚未启用。
          </Typography.Text>
        </div>
      </main>
    </div>
  )
}
