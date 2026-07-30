/**
 * 核销台。
 *
 * 刻意分两步（查验 → 确认核销）：现实中核销员需先确认券有效再执行不可逆操作；
 * 同时让 SC-004 的演示更清晰 —— 第二次点核销时能明确看到「已核销」。
 *
 * 输入框自动转大写并过滤 0O1IL：券码字符集不含这些字符（ADR-010），
 * 提前过滤可减少人工输入错误。
 */

import { Alert, Button, Card, Descriptions, Input, Result, Space, Typography } from 'antd'
import { useState } from 'react'
import { ApiError, api } from '../api/client'
import { ERROR_MESSAGE } from '../api/types'
import type { RedeemCheck, RedeemResult } from '../api/types'

type Outcome =
  | { kind: 'success'; data: RedeemResult }
  | { kind: 'warning'; code: string; text: string }
  | { kind: 'error'; code: string; text: string }

const CLEAN = /[^23456789ABCDEFGHJKMNPQRSTVWXYZ]/g

export default function VerifyPage() {
  const [code, setCode] = useState('')
  const [check, setCheck] = useState<RedeemCheck | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [busy, setBusy] = useState(false)

  const reset = () => {
    setCheck(null)
    setOutcome(null)
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
    } catch (e) {
      const err = e as ApiError
      const text = ERROR_MESSAGE[err.code] ?? err.message
      // 已核销 / 已过期 属预期的业务结果，用警告色而非错误色
      const kind = err.code === 'COUPON_NOT_FOUND' ? 'error' : 'warning'
      setOutcome({ kind, code: err.code, text })
      setCheck(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%', maxWidth: 720 }}>
      <Card title="核销台">
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="核销由核销人员执行，用户仅出示券码。核销无需校验券的归属，因此券码本身不可预测。"
        />
        <Space.Compact style={{ width: '100%' }}>
          <Input
            size="large"
            placeholder="输入券码，例如 7K4MPQ2XZ9"
            value={code}
            maxLength={10}
            onChange={(e) => setCode(e.target.value.toUpperCase().replace(CLEAN, ''))}
            onPressEnter={doCheck}
            style={{ letterSpacing: 4 }}
          />
          <Button size="large" type="default" onClick={doCheck} loading={busy} disabled={code.length !== 10}>
            查验
          </Button>
        </Space.Compact>
        <Typography.Text type="secondary">
          券码为 10 位，不含容易混淆的 0 O 1 I L，输入时会自动过滤
        </Typography.Text>
      </Card>

      {check && (
        <Card
          title="查验结果"
          extra={
            <Button type="primary" danger onClick={doRedeem} loading={busy} disabled={!check.redeemable}>
              确认核销
            </Button>
          }
        >
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="券码">{check.code}</Descriptions.Item>
            <Descriptions.Item label="活动">{check.campaign_name}</Descriptions.Item>
            <Descriptions.Item label="面额">¥{check.face_value}</Descriptions.Item>
            <Descriptions.Item label="当前状态">{check.display_status}</Descriptions.Item>
            <Descriptions.Item label="持有人">{check.owner}</Descriptions.Item>
            <Descriptions.Item label="可否核销">
              {check.redeemable ? '可核销' : `不可核销：${check.reason}`}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {outcome && (
        <Card>
          {outcome.kind === 'success' ? (
            <Result
              status="success"
              title="核销成功"
              subTitle={`面额 ¥${outcome.data.face_value} · 核销人 ${outcome.data.used_by} · ${new Date(
                outcome.data.used_at,
              ).toLocaleString()}`}
              extra={<Button onClick={reset}>继续核销下一张</Button>}
            />
          ) : (
            <Result
              status={outcome.kind}
              title={outcome.text}
              subTitle={`错误码 ${outcome.code}`}
              extra={<Button onClick={reset}>重新输入</Button>}
            />
          )}
        </Card>
      )}
    </Space>
  )
}
