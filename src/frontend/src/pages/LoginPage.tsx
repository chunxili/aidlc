import { Button, Checkbox, Form, Input, Tabs, Typography, App as AntApp } from 'antd'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { landingFor, useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'
import { ERROR_MESSAGE } from '../api/types'
import { BRAND } from '../theme'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [loading, setLoading] = useState(false)

  const submit = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      const user = await login(values.username.trim(), values.password)
      navigate(landingFor(user), { replace: true })
    } catch (e) {
      if (e instanceof ApiError) {
        // 申请被驳回时把原因原样告知，用户才知道要补什么材料
        message.error(
          e.code === 'ACCOUNT_REJECTED' ? e.message : ERROR_MESSAGE[e.code] ?? '账号或密码有误',
        )
      } else {
        message.error('登录失败，请稍后重试')
      }
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
            满减券与折扣券灵活配置，库存精准管控，门店即时核销，风险自动识别。
          </div>
          <div className="auth__metrics">
            <div>
              <div className="auth__metric-value">22</div>
              <div className="auth__metric-label">广州门店</div>
            </div>
            <div>
              <div className="auth__metric-value">99.99%</div>
              <div className="auth__metric-label">库存准确率</div>
            </div>
            <div>
              <div className="auth__metric-value">7×24</div>
              <div className="auth__metric-label">风控值守</div>
            </div>
          </div>
        </div>

        <div className="auth__foot">© 2026 {BRAND.full}</div>
      </aside>

      <main className="auth__panel">
        <div className="auth__form">
          <Tabs
            activeKey="login"
            onChange={(k) => k === 'register' && navigate('/register')}
            items={[
              { key: 'login', label: '登录' },
              { key: 'register', label: '注册' },
            ]}
          />

          <Form layout="vertical" onFinish={submit} requiredMark={false} size="large">
            <Form.Item
              name="username"
              label="账号"
              rules={[{ required: true, message: '请输入账号' }]}
            >
              <Input placeholder="请输入账号" autoComplete="username" autoFocus />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password placeholder="请输入密码" autoComplete="current-password" />
            </Form.Item>
            <Form.Item style={{ marginBottom: 20 }}>
              <div
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
              >
                <Checkbox defaultChecked>记住账号</Checkbox>
                <Typography.Link disabled style={{ fontSize: 13 }}>
                  忘记密码
                </Typography.Link>
              </div>
            </Form.Item>
            <Form.Item style={{ marginBottom: 16 }}>
              <Button type="primary" htmlType="submit" block loading={loading}>
                登录
              </Button>
            </Form.Item>
          </Form>

          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            还没有账号？<Link to="/register">立即注册</Link>
          </Typography.Text>
        </div>
      </main>
    </div>
  )
}
