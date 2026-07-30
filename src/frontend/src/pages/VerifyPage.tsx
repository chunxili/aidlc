/**
 * 券码核销台。
 *
 * 两步操作（查验 → 确认核销）：核销不可逆，门店场景下需先确认券有效再执行。
 * 引入券型后必须录入订单金额：没有它既无法判断使用门槛，也无法算折扣券的优惠额。
 */

import {
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  InputNumber,
  Result,
  Row,
  Statistic,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import { ApiError, api } from '../api/client'
import { COUPON_TYPE_LABEL, ERROR_MESSAGE } from '../api/types'
import type { RedeemCheck, RedeemResult } from '../api/types'
import { PageHeader } from '../components/PageHeader'

type Outcome =
  | { kind: 'success'; data: RedeemResult }
  | { kind: 'warning'; code: string; text: string }
  | { kind: 'error'; code: string; text: string }

/** 券码字符集不含 0 O 1 I L，输入时直接过滤，减少人工录入错误 */
const CLEAN = /[^23456789ABCDEFGHJKMNPQRSTVWXYZ]/g

export default function VerifyPage() {
  const [code, setCode] = useState('')
  const [amount, setAmount] = useState<number | null>(null)
  const [check, setCheck] = useState<RedeemCheck | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [busy, setBusy] = useState(false)
  const [stats, setStats] = useState({ count: 0, discount: 0 })

  const reset = (clearInput = false) => {
    setCheck(null)
    setOutcome(null)
    if (clearInput) {
      setCode('')
      setAmount(null)
    }
  }

  const doCheck = async () => {
    reset()
    setBusy(true)
    try {
      setCheck(await api.get<RedeemCheck>(`/api/redemptions/${code}`))
    } catch (e) {
      const err = e as ApiError
      setOutcome({ kind: 'error', code: err.code, text: ERROR_MESSAGE[err.code] ?? err.message })
    } finally {
      setBusy(false)
    }
  }

  const doRedeem = async () => {
    if (amount === null) return
    setBusy(true)
    try {
      const data = await api.post<RedeemResult>('/api/redemptions', {
        code,
        order_amount: String(amount),
      })
      setOutcome({ kind: 'success', data })
      setCheck(null)
      setStats((s) => ({
        count: s.count + 1,
        discount: s.discount + Number(data.discount_amount),
      }))
    } catch (e) {
      const err = e as ApiError
      setOutcome({
        kind: err.code === 'COUPON_NOT_FOUND' ? 'error' : 'warning',
        code: err.code,
        // 未达门槛时后端会给出具体门槛金额，比通用文案更有用
        text: err.code === 'ORDER_AMOUNT_BELOW_THRESHOLD' ? err.message : ERROR_MESSAGE[err.code] ?? err.message,
      })
      setCheck(null)
    } finally {
      setBusy(false)
    }
  }

  const threshold = check ? Number(check.min_order_amount) : 0
  const amountOk = amount !== null && amount > 0 && amount >= threshold

  return (
    <>
      <PageHeader
        title="券码核销"
        description="录入顾客出示的券码与本单金额，确认无误后完成核销"
        extra={
          <Row gutter={24}>
            <Col>
              <Statistic title="本次登录已核销" value={stats.count} suffix="张" />
            </Col>
            <Col>
              <Statistic
                title="累计优惠"
                value={stats.discount}
                precision={2}
                prefix="¥"
              />
            </Col>
          </Row>
        }
      />

      <Row gutter={16}>
        <Col xs={24} lg={13}>
          <Card>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              券码
            </Typography.Text>
            <Input
              className="mono"
              size="large"
              placeholder="10 位券码"
              value={code}
              maxLength={10}
              onChange={(e) => setCode(e.target.value.toUpperCase().replace(CLEAN, ''))}
              onPressEnter={() => code.length === 10 && doCheck()}
              style={{ marginTop: 6, fontSize: 22, letterSpacing: 4, textAlign: 'center' }}
              autoFocus
            />
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginTop: 8,
              }}
            >
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {code.length}/10 · 不含 0 O 1 I L
              </Typography.Text>
              <Typography.Link onClick={() => reset(true)} style={{ fontSize: 13 }}>
                清空
              </Typography.Link>
            </div>
            <Button
              type="primary"
              size="large"
              block
              style={{ marginTop: 16 }}
              onClick={doCheck}
              loading={busy && !check}
              disabled={code.length !== 10}
            >
              查验券码
            </Button>
          </Card>
        </Col>

        <Col xs={24} lg={11}>
          {check && (
            <Card
              title="券码信息"
              extra={
                <Tag color={check.redeemable ? 'green' : 'default'}>{check.display_status}</Tag>
              }
            >
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="优惠活动">{check.campaign_name}</Descriptions.Item>
                <Descriptions.Item label="券型">
                  <Tag color={check.coupon_type === 'CASH' ? 'volcano' : 'geekblue'}>
                    {COUPON_TYPE_LABEL[check.coupon_type]}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="优惠内容">
                  <Typography.Text strong>{check.benefit_text}</Typography.Text>
                </Descriptions.Item>
                <Descriptions.Item label="持有会员">{check.owner}</Descriptions.Item>
              </Descriptions>

              {check.redeemable ? (
                <>
                  <div style={{ marginTop: 16 }}>
                    <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                      本单金额（元）
                    </Typography.Text>
                    <InputNumber
                      size="large"
                      min={0.01}
                      precision={2}
                      value={amount}
                      onChange={setAmount}
                      style={{ width: '100%', marginTop: 6 }}
                      placeholder="请输入本单实付前金额"
                      onPressEnter={() => amountOk && doRedeem()}
                    />
                    {threshold > 0 && (
                      <Typography.Text
                        type={amount !== null && amount < threshold ? 'danger' : 'secondary'}
                        style={{ fontSize: 12 }}
                      >
                        该券需满 {threshold} 元可用
                      </Typography.Text>
                    )}
                  </div>
                  <Button
                    type="primary"
                    danger
                    size="large"
                    block
                    style={{ marginTop: 16 }}
                    onClick={doRedeem}
                    loading={busy}
                    disabled={!amountOk}
                  >
                    确认核销
                  </Button>
                </>
              ) : (
                <Typography.Paragraph type="danger" style={{ marginTop: 16, marginBottom: 0 }}>
                  该券不可核销：{check.reason}
                </Typography.Paragraph>
              )}
            </Card>
          )}

          {outcome && (
            <Card>
              {outcome.kind === 'success' ? (
                <Result
                  status="success"
                  title="核销成功"
                  subTitle={
                    <>
                      本单 ¥{Number(outcome.data.order_amount)} · 优惠 ¥
                      {Number(outcome.data.discount_amount)} · 应付 ¥
                      {Number(outcome.data.payable_amount)}
                      <br />
                      {outcome.data.store_name} · {outcome.data.used_by} ·{' '}
                      {new Date(outcome.data.used_at).toLocaleString('zh-CN')}
                    </>
                  }
                  extra={
                    <Button type="primary" onClick={() => reset(true)}>
                      核销下一张
                    </Button>
                  }
                />
              ) : (
                <Result
                  status={outcome.kind}
                  title={outcome.text}
                  extra={<Button onClick={() => reset(true)}>重新录入</Button>}
                />
              )}
            </Card>
          )}

          {!check && !outcome && (
            <Card style={{ background: '#fafbfc', borderStyle: 'dashed' }}>
              <Typography.Paragraph type="secondary" style={{ margin: 0, fontSize: 13 }}>
                录入券码后将显示券型、优惠内容与使用门槛，再填写本单金额即可核销。
              </Typography.Paragraph>
            </Card>
          )}
        </Col>
      </Row>
    </>
  )
}
