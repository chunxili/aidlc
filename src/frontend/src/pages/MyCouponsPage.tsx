/**
 * 我的券。
 *
 * 倒计时归零时**自动刷新该行**，配合后端的惰性过期（ADR-002），
 * 使 SC-003「过期券核销」的演示无需手动刷新页面。
 */

import { Alert, Card, Segmented, Table, Tag, Typography } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Coupon, Paged } from '../api/types'

const FILTERS = ['全部', '可用', '已核销', '已过期'] as const

function Countdown({ expiresAt, onExpire }: { expiresAt: string; onExpire: () => void }) {
  const [left, setLeft] = useState(() => Date.parse(expiresAt) - Date.now())
  const fired = useRef(false)

  useEffect(() => {
    const timer = setInterval(() => {
      const ms = Date.parse(expiresAt) - Date.now()
      setLeft(ms)
      if (ms <= 0 && !fired.current) {
        fired.current = true
        onExpire()
      }
    }, 1000)
    return () => clearInterval(timer)
  }, [expiresAt, onExpire])

  if (left <= 0) return <Typography.Text type="secondary">已过期</Typography.Text>
  const total = Math.floor(left / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return (
    <Typography.Text type={m < 5 ? 'danger' : undefined}>
      {m > 60 ? `${Math.floor(m / 60)} 小时 ${m % 60} 分` : `${m} 分 ${s} 秒`}
    </Typography.Text>
  )
}

export default function MyCouponsPage() {
  const [data, setData] = useState<Paged<Coupon> | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('全部')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const qs = filter === '全部' ? '' : `?display_status=${encodeURIComponent(filter)}`
      setData(await api.get<Paged<Coupon>>(`/api/coupons/my${qs}`))
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <Card
      title="我的优惠券"
      extra={<Segmented options={[...FILTERS]} value={filter} onChange={(v) => setFilter(v as never)} />}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="券的过期由时间实时判断，数据库中不存储「已过期」状态。倒计时归零后本页会自动刷新状态。"
      />
      <Table
        rowKey="id"
        loading={loading}
        dataSource={data?.items ?? []}
        pagination={{ total: data?.total ?? 0, pageSize: data?.page_size ?? 20 }}
        columns={[
          {
            title: '券码',
            dataIndex: 'code',
            render: (v: string) => (
              <Typography.Text copyable strong style={{ letterSpacing: 2 }}>
                {v}
              </Typography.Text>
            ),
          },
          { title: '活动', dataIndex: 'campaign_name' },
          { title: '面额', dataIndex: 'face_value', render: (v: string) => `¥${v}` },
          {
            title: '状态',
            dataIndex: 'display_status',
            render: (v: Coupon['display_status']) => (
              <Tag color={v === '可用' ? 'green' : v === '已核销' ? 'blue' : 'default'}>{v}</Tag>
            ),
          },
          {
            title: '剩余有效期',
            render: (_, r) =>
              r.display_status === '可用' ? (
                <Countdown expiresAt={r.expires_at} onExpire={load} />
              ) : (
                <Typography.Text type="secondary">—</Typography.Text>
              ),
          },
          {
            title: '过期时间',
            dataIndex: 'expires_at',
            render: (v: string) => new Date(v).toLocaleString(),
          },
        ]}
      />
    </Card>
  )
}
