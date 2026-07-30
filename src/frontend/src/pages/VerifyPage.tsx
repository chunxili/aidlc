/**
 * 券码核销台。
 *
 * 两步操作（查验 → 确认核销）：核销不可逆，门店场景下需先确认券有效再执行。
 */

import {
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  Result,
  Row,
  Statistic,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import { ApiError, api } from '../api/client'
import { ERROR_MESSAGE } from '../api/types'
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
  const [check, setCheck] = useState<RedeemCheck | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [busy, setBusy] = useState(false)
  const [today, setToday] = useState(0)

  const reset = (clearCode = false) => {
    setCheck(null)
    setOutcome(null)
    if (clearCode) setCode('')
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
    setBusy(true)
    try {
      const data = await api.post<RedeemResult>('/api/redemptions', { code })
      setOutcome({ kind: 'success', data })
      setCheck(null)
      setToday((n) => n + 1)
    } catch (e) {
      const err = e as ApiError
      setOutcome({
        kind: err.code === 'COUPON_NOT_FOUND' ? 'error' : 'warning',
        code: err.code,
        text: ERROR_MESSAGE[err.code] ?? err.message,
      })
      setCheck(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title="券码核销"
        description="录入顾客出示的券码，确认无误后完成核销"
        extra={<Statistic title="本次登录已核销" value={today} suffix="张" />}
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
              extra={<Tag color={check.redeemable ? 'green' : 'default'}>{check.display_status}</Tag>}
            >
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="优惠活动">{check.campaign_name}</Descriptions.Item>
                <Descriptions.Item label="面额">
                  <Typography.Text strong>¥{Number(check.face_value)}</Typography.Text>
                </Descriptions.Item>
                <Descriptions.Item label="持有会员">{check.owner}</Descriptions.Item>
              </Descriptions>
              {check.redeemable ? (
                <Button
                  type="primary"
                  danger
                  size="large"
                  block
                  style={{ marginTop: 16 }}
                  onClick={doRedeem}
                  loading={busy}
                >
                  确认核销
                </Button>
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
                      面额 ¥{Number(outcome.data.face_value)} · 操作人 {outcome.data.used_by}
                      <br />
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
                  extra={
                    <Button onClick={() => reset(true)}>重新录入</Button>
                  }
                />
              )}
            </Card>
          )}

          {!check && !outcome && (
            <Card style={{ background: '#fafbfc', borderStyle: 'dashed' }}>
              <Typography.Paragraph type="secondary" style={{ margin: 0, fontSize: 13 }}>
                录入券码后将显示优惠活动、面额与持有会员信息，确认后再执行核销。
              </Typography.Paragraph>
            </Card>
          )}
        </Col>
      </Row>
    </>
  )
}
