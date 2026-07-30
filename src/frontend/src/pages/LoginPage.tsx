import { Button, Checkbox, Form, Input, App as AntApp } from 'antd'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { landingFor, useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'
import { ERROR_MESSAGE } from '../api/types'
import { Ticket } from '../components/Ticket'

/** 「记住账号」只记账号，不记密码。 */
const REMEMBER_KEY = 'huima.remembered_username'

function readRemembered(): string {
  try {
    return localStorage.getItem(REMEMBER_KEY) ?? ''
  } catch {
    return '' // 隐私模式下 localStorage 会抛错，此时当作没记住
  }
}

function writeRemembered(username: string | null) {
  try {
    if (username) localStorage.setItem(REMEMBER_KEY, username)
    else localStorage.removeItem(REMEMBER_KEY)
  } catch {
    /* 存不下就算了，不影响登录 */
  }
}

/** 券身背面的适用范围：四类账号各自进入后能做什么，照实写。 */
const SCOPE = [
  { role: '会员', can: '领取优惠券，查看和使用自己的券' },
  { role: '核销员', can: '在所属门店核销顾客出示的券码' },
  { role: '运营', can: '配置优惠活动，处理风险名单，看投放数据' },
  { role: '管理员', can: '审核注册申请，管理门店核销人员' },
]

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [loading, setLoading] = useState(false)
  const [remembered] = useState(readRemembered)

  const submit = async (values: { username: string; password: string; remember: boolean }) => {
    const username = values.username.trim()
    setLoading(true)
    try {
      const user = await login(username, values.password)
      writeRemembered(values.remember ? username : null)
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
    <Ticket
      headline="一张券，从发出到核销都在这里"
      stubTitle="登录"
      stubAction={<Link to="/register">注册新账号</Link>}
      stub={
        <>
          <Form
            layout="vertical"
            onFinish={submit}
            requiredMark={false}
            size="large"
            initialValues={{ username: remembered, remember: Boolean(remembered) }}
          >
            <Form.Item
              name="username"
              label="账号"
              rules={[{ required: true, message: '请输入账号' }]}
            >
              <Input placeholder="请输入账号" autoComplete="username" autoFocus={!remembered} />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password
                placeholder="请输入密码"
                autoComplete="current-password"
                autoFocus={Boolean(remembered)}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 20 }}>
              <div className="tk__row">
                <Form.Item name="remember" valuePropName="checked" noStyle>
                  <Checkbox>记住账号</Checkbox>
                </Form.Item>
                <span className="tk__hint">忘记密码请联系管理员重置</span>
              </div>
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button type="primary" htmlType="submit" block loading={loading}>
                登录
              </Button>
            </Form.Item>
          </Form>

          <div className="tk__stub-foot">
            <span className="tk__hint">
              核销员与运营账号需管理员审核通过后才能登录。
            </span>
          </div>
        </>
      }
    >
      <dl className="tk__terms">
        {SCOPE.map((s) => (
          <div className="tk__term" key={s.role}>
            <dt className="tk__term-k">{s.role}</dt>
            <dd className="tk__term-v">{s.can}</dd>
          </div>
        ))}
      </dl>
    </Ticket>
  )
}
