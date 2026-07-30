import { Badge, Card, Empty, Segmented, Table, Tag, Typography } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { COUPON_TYPE_LABEL } from '../api/types'
import type { Coupon, Paged } from '../api/types'
import { PageHeader } from '../components/PageHeader'

const FILTERS = ['全部', '可用', '已核销', '已过期'] as const

/** 有效期倒计时。归零时通知父级刷新，使状态无需手动刷新页面即更新。 */
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

  if (left <= 0) return <Typography.Text type="secondary">已到期</Typography.Text>

  const total = Math.floor(left / 1000)
  const d = Math.floor(total / 86400)
  const h = Math.floor((total % 86400) / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60

  if (d > 0) return <Typography.Text>{`${d} 天 ${h} 小时`}</Typography.Text>
  if (h > 0) return <Typography.Text>{`${h} 小时 ${m} 分`}</Typography.Text>
  return (
    <Typography.Text type={m < 5 ? 'danger' : undefined} className="mono">
      {`${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`}
    </Typography.Text>
  )
}

const STATUS_COLOR: Record<Coupon['display_status'], string> = {
  可用: 'green',
  已核销: 'default',
  已过期: 'default',
}

export default function MyCouponsPage() {
  const [data, setData] = useState<Paged<Coupon> | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('全部')
  const [counts, setCounts] = useState({ 可用: 0, 已核销: 0, 已过期: 0 })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page_size: '50' })
      if (filter !== '全部') params.set('display_status', filter)
      // page_size 上限由后端约束为 100（le=100）。此处取满 100 用于统计各状态数量，
      // 超过 100 会返回 422 并使整个 Promise.all 失败、列表空白 —— 这正是"我的优惠券
      // 一张都不显示"的根因。演示规模下单用户券数远小于 100，统计足够准确。
      const [page, all] = await Promise.all([
        api.get<Paged<Coupon>>(`/api/coupons/my?${params.toString()}`),
        api.get<Paged<Coupon>>('/api/coupons/my?page_size=100'),
      ])
      setData(page)
      setCounts({
        可用: all.items.filter((i) => i.display_status === '可用').length,
        已核销: all.items.filter((i) => i.display_status === '已核销').length,
        已过期: all.items.filter((i) => i.display_status === '已过期').length,
      })
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <>
      <PageHeader
        title="我的优惠券"
        description={`可用 ${counts.可用} 张 · 已核销 ${counts.已核销} 张 · 已过期 ${counts.已过期} 张`}
      />

      <Card
        extra={
          <Segmented
            size="small"
            options={FILTERS.map((f) => ({
              value: f,
              label:
                f === '全部' ? (
                  '全部'
                ) : (
                  <Badge
                    count={counts[f]}
                    size="small"
                    offset={[8, -2]}
                    styles={{ indicator: { boxShadow: 'none' } }}
                  >
                    <span style={{ paddingRight: counts[f] ? 10 : 0 }}>{f}</span>
                  </Badge>
                ),
            }))}
            value={filter}
            onChange={(v) => setFilter(v as never)}
          />
        }
      >
        <Table
          rowKey="id"
          loading={loading}
          dataSource={data?.items ?? []}
          locale={{
            emptyText: (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无优惠券" />
            ),
          }}
          pagination={data && data.total > 50 ? { total: data.total, pageSize: 50 } : false}
          columns={[
            {
              title: '券码',
              dataIndex: 'code',
              width: 190,
              render: (v: string) => (
                <Typography.Text className="mono" copyable strong>
                  {v}
                </Typography.Text>
              ),
            },
            { title: '优惠活动', dataIndex: 'campaign_name', ellipsis: true },
            {
              title: '优惠内容',
              dataIndex: 'benefit_text',
              width: 200,
              render: (v: string, r) => (
                <div>
                  <Typography.Text strong>{v}</Typography.Text>
                  <div>
                    <Tag
                      color={r.coupon_type === 'CASH' ? 'volcano' : 'geekblue'}
                      style={{ marginTop: 2 }}
                    >
                      {COUPON_TYPE_LABEL[r.coupon_type]}
                    </Tag>
                  </div>
                </div>
              ),
            },
            {
              title: '状态',
              dataIndex: 'display_status',
              width: 100,
              render: (v: Coupon['display_status']) => <Tag color={STATUS_COLOR[v]}>{v}</Tag>,
            },
            {
              title: '剩余时间',
              width: 130,
              render: (_, r) =>
                r.display_status === '可用' ? (
                  <Countdown expiresAt={r.expires_at} onExpire={load} />
                ) : (
                  <Typography.Text type="secondary">—</Typography.Text>
                ),
            },
            {
              title: '有效期至',
              dataIndex: 'expires_at',
              width: 180,
              render: (v: string) => (
                <Typography.Text type="secondary">
                  {new Date(v).toLocaleString('zh-CN')}
                </Typography.Text>
              ),
            },
          ]}
        />
      </Card>
    </>
  )
}
