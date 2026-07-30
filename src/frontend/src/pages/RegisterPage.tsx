import { Alert, Button, Cascader, Form, Input, Segmented, App as AntApp } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import { landingFor, useAuth } from '../auth/AuthContext'
import { ERROR_MESSAGE } from '../api/types'
import type { RegisterResult, RegisterRole, Store } from '../api/types'
import { Ticket } from '../components/Ticket'

const ROLE_OPTIONS: { value: RegisterRole; label: string; hint: string }[] = [
  { value: 'USER', label: '会员', hint: '注册后即可领取和使用优惠券' },
  { value: 'VERIFIER', label: '门店核销员', hint: '需选择所属门店，提交后由管理员审核' },
  { value: 'OPERATOR', label: '运营人员', hint: '可创建优惠活动，提交后由管理员审核' },
]

export default function RegisterPage() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const { message } = AntApp.useApp()
  const [role, setRole] = useState<RegisterRole>('USER')
  const [stores, setStores] = useState<Store[]>([])
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()

  useEffect(() => {
    if (role !== 'VERIFIER' || stores.length) return
    api.get<Store[]>('/api/stores').then(setStores).catch(() => setStores([]))
  }, [role, stores.length])

  // 门店按行政区分组，广州 20+ 家门店平铺选择会很难找
  const storeOptions = useMemo(() => {
    const byDistrict = new Map<string, Store[]>()
    for (const s of stores) {
      byDistrict.set(s.district, [...(byDistrict.get(s.district) ?? []), s])
    }
    return [...byDistrict.entries()].map(([district, list]) => ({
      value: district,
      label: district,
      children: list.map((s) => ({ value: s.id, label: `${s.name}（${s.code}）` })),
    }))
  }, [stores])

  const currentHint = ROLE_OPTIONS.find((r) => r.value === role)!.hint

  const submit = async (values: Record<string, unknown>) => {
    setLoading(true)
    try {
      const storePath = values.store as [string, number] | undefined
      const password = values.password as string
      const result = await api.post<RegisterResult>('/api/auth/register', {
        username: (values.username as string).trim(),
        password,
        display_name: (values.display_name as string).trim(),
        role,
        phone: (values.phone as string) || null,
        store_id: role === 'VERIFIER' ? storePath?.[1] : null,
      })

      // 注册成功即自动登录：待审核用户会落到进度页，会员直接进业务页
      const user = await login((values.username as string).trim(), password)
      message.success(
        result.needs_approval ? '提交成功，正在等待管理员审核' : `欢迎加入，${user.display_name}`,
      )
      navigate(landingFor(user), { replace: true })
    } catch (e) {
      if (e instanceof ApiError) {
        message.error(ERROR_MESSAGE[e.code] ?? e.message)
      } else {
        message.error('注册失败，请稍后重试')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <Ticket
      headline="先领一个账号，再领券"
      stubTitle="注册"
      stubAction={<Link to="/login">已有账号，去登录</Link>}
      stub={
        <>
          <Segmented
            block
            value={role}
            onChange={(v) => setRole(v as RegisterRole)}
            options={ROLE_OPTIONS.map((r) => ({ value: r.value, label: r.label }))}
            style={{ marginBottom: 8 }}
          />
          <Alert type="info" showIcon message={currentHint} style={{ marginBottom: 16 }} />

          <Form form={form} layout="vertical" onFinish={submit} requiredMark={false} size="large">
            <Form.Item
              name="username"
              label="账号"
              rules={[
                { required: true, message: '请输入账号' },
                { min: 4, message: '账号至少 4 个字符' },
              ]}
            >
              <Input placeholder="4 位以上，字母或数字" autoComplete="username" />
            </Form.Item>
            <Form.Item
              name="display_name"
              label="姓名"
              rules={[{ required: true, message: '请输入姓名' }]}
            >
              <Input placeholder="真实姓名" />
            </Form.Item>
            <Form.Item
              name="phone"
              label="手机号"
              rules={[{ pattern: /^1\d{10}$/, message: '请输入 11 位手机号' }]}
            >
              <Input placeholder="选填" maxLength={11} />
            </Form.Item>

            {role === 'VERIFIER' && (
              <Form.Item
                name="store"
                label="所属门店"
                rules={[{ required: true, message: '请选择所属门店' }]}
              >
                <Cascader
                  options={storeOptions}
                  placeholder="先选行政区，再选门店"
                  showSearch={{
                    filter: (input, path) =>
                      path.some((o) => String(o.label).toLowerCase().includes(input.toLowerCase())),
                  }}
                />
              </Form.Item>
            )}

            <Form.Item
              name="password"
              label="密码"
              rules={[
                { required: true, message: '请设置密码' },
                { min: 8, message: '密码至少 8 个字符' },
              ]}
            >
              <Input.Password placeholder="至少 8 位" autoComplete="new-password" />
            </Form.Item>
            <Form.Item
              name="password2"
              label="确认密码"
              dependencies={['password']}
              rules={[
                { required: true, message: '请再次输入密码' },
                ({ getFieldValue }) => ({
                  validator: (_, value) =>
                    !value || getFieldValue('password') === value
                      ? Promise.resolve()
                      : Promise.reject(new Error('两次输入的密码不一致')),
                }),
              ]}
            >
              <Input.Password placeholder="再次输入密码" autoComplete="new-password" />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }}>
              <Button type="primary" htmlType="submit" block loading={loading}>
                {role === 'USER' ? '注册并登录' : '提交申请'}
              </Button>
            </Form.Item>
          </Form>
        </>
      }
    >
      <p className="tk__note">
        会员注册后立刻能领券。门店核销员要选所属门店，运营人员要说明投放范围，
        这两类账号提交后由管理员审核，通过前无法登录。
      </p>
    </Ticket>
  )
}
