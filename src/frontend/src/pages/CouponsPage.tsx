import {
  Button,
  Card,
  Col,
  Empty,
  Modal,
  Result,
  Row,
  Segmented,
  Skeleton,
  Space,
  Tag,
  Typography,
  App as AntApp,
} from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import { CATEGORY_LABEL, COUPON_TYPE_LABEL, ERROR_MESSAGE } from '../api/types'
import type {
  AvailableCampaign,
  Category,
  ClaimResult,
  CouponType,
  RecommendationResult,
} from '../api/types'
import { PageHeader } from '../components/PageHeader'

const FILTERS: (Category | '全部')[] = ['全部', 'FOOD', 'TRAVEL', 'SHOPPING', 'LIFE']

function minutesLabel(m: number) {
  if (m < 60) return `${m} 分钟内使用`
  if (m < 1440) return `${Math.round(m / 60)} 小时内使用`
  return `${Math.round(m / 1440)} 天内使用`
}

/**
 * 券面主视觉。满减券突出减免金额，折扣券突出折数 ——
 * 折扣券没有固定面额，硬要显示"¥null"会很难看。
 */
function Benefit({
  item,
}: {
  item: { coupon_type: CouponType; face_value: string | null; benefit_text: string }
}) {
  if (item.coupon_type === 'CASH') {
    return (
      <div className="coupon-card__amount">
        <span className="coupon-card__symbol">¥</span>
        <span className="coupon-card__value">{Number(item.face_value ?? 0)}</span>
      </div>
    )
  }
  const match = /([\d.]+)\s*折/.exec(item.benefit_text)
  return (
    <div className="coupon-card__amount">
      <span className="coupon-card__value">{match ? match[1] : '—'}</span>
      <span className="coupon-card__symbol">折</span>
    </div>
  )
}

export default function CouponsPage() {
  const { message, notification } = AntApp.useApp()
  const navigate = useNavigate()
  const [recs, setRecs] = useState<RecommendationResult | null>(null)
  const [campaigns, setCampaigns] = useState<AvailableCampaign[]>([])
  const [loading, setLoading] = useState(true)
  const [recLoading, setRecLoading] = useState(true)
  const [claimed, setClaimed] = useState<ClaimResult | null>(null)
  const [filter, setFilter] = useState<Category | '全部'>('全部')
  const [claiming, setClaiming] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setRecLoading(true)
    try {
      const [r, c] = await Promise.all([
        api.get<RecommendationResult>('/api/recommendations?limit=3'),
        api.get<AvailableCampaign[]>('/api/campaigns/available'),
      ])
      setRecs(r)
      setCampaigns(c)
    } finally {
      setLoading(false)
      setRecLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const claim = async (id: number) => {
    setClaiming(id)
    try {
      setClaimed(await api.post<ClaimResult>('/api/coupons/claim', { campaign_id: id }))
      void load()
    } catch (e) {
      if (!(e instanceof ApiError)) {
        message.error('领取失败，请稍后重试')
        return
      }
      const text = ERROR_MESSAGE[e.code] ?? e.message
      if (e.code === 'RISK_BLOCKED' || e.code === 'RISK_MANUAL_REVIEW') {
        notification.warning({ message: '暂时无法领取', description: text, duration: 8 })
      } else {
        message.warning(text)
      }
      void load()
    } finally {
      setClaiming(null)
    }
  }

  const shown = useMemo(
    () => (filter === '全部' ? campaigns : campaigns.filter((c) => c.category === filter)),
    [campaigns, filter],
  )

  return (
    <>
      <PageHeader title="领券中心" description="为你精选的优惠，先领先用" />

      {/* 精选推荐：位于领取入口之前，用户在决策前即看到推荐依据 */}
      <Card
        title="为你精选"
        style={{ marginBottom: 16 }}
        extra={
          recs?.degraded ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              热门优先
            </Typography.Text>
          ) : null
        }
      >
        {recLoading ? (
          <Skeleton active paragraph={{ rows: 2 }} />
        ) : !recs?.items.length ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无推荐" />
        ) : (
          <Row gutter={[16, 16]}>
            {recs.items.map((r) => (
              <Col key={r.campaign_id} xs={24} md={12} lg={8}>
                <Card className="coupon-card" size="small" hoverable>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                    <div style={{ minWidth: 0 }}>
                      <Benefit item={r} />
                      <Typography.Text strong ellipsis style={{ display: 'block', marginTop: 2 }}>
                        {r.campaign_name}
                      </Typography.Text>
                      <Space size={4} style={{ marginTop: 6 }}>
                        <Tag>{CATEGORY_LABEL[r.category]}</Tag>
                        <Tag color={r.coupon_type === 'CASH' ? 'volcano' : 'geekblue'}>
                          {COUPON_TYPE_LABEL[r.coupon_type]}
                        </Tag>
                      </Space>
                    </div>
                    <Button
                      type="primary"
                      onClick={() => claim(r.campaign_id)}
                      loading={claiming === r.campaign_id}
                    >
                      立即领取
                    </Button>
                  </div>
                  <Typography.Text strong style={{ display: 'block', marginTop: 10, fontSize: 13 }}>
                    {r.benefit_text}
                  </Typography.Text>
                  <Typography.Paragraph
                    type="secondary"
                    ellipsis={{ rows: 2 }}
                    style={{ margin: '6px 0 0', fontSize: 12.5, minHeight: 38 }}
                  >
                    {r.reason}
                  </Typography.Paragraph>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    仅剩 {r.remaining_stock} 张
                  </Typography.Text>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      <Card
        title="全部优惠"
        extra={
          <Segmented
            size="small"
            value={filter}
            onChange={(v) => setFilter(v as Category | '全部')}
            options={FILTERS.map((f) => ({
              value: f,
              label: f === '全部' ? '全部' : CATEGORY_LABEL[f],
            }))}
          />
        }
      >
        {loading ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : !shown.length ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可领优惠" />
        ) : (
          <Row gutter={[16, 16]}>
            {shown.map((c) => {
              const left = c.per_user_limit - c.my_claimed_count
              return (
                <Col key={c.id} xs={24} md={12} lg={8}>
                  <Card className="coupon-card" size="small">
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                      <div style={{ minWidth: 0 }}>
                        <Benefit item={c} />
                        <Typography.Text strong ellipsis style={{ display: 'block', marginTop: 2 }}>
                          {c.name}
                        </Typography.Text>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {c.benefit_text}
                        </Typography.Text>
                      </div>
                      <Button
                        type="primary"
                        onClick={() => claim(c.id)}
                        loading={claiming === c.id}
                        disabled={left <= 0}
                      >
                        {left <= 0 ? '已领完' : '立即领取'}
                      </Button>
                    </div>
                    <Space size={6} wrap style={{ marginTop: 12 }}>
                      <Tag>{CATEGORY_LABEL[c.category]}</Tag>
                      <Tag color={c.coupon_type === 'CASH' ? 'volcano' : 'geekblue'}>
                        {COUPON_TYPE_LABEL[c.coupon_type]}
                      </Tag>
                      <Tag color="orange">{minutesLabel(c.validity_minutes)}</Tag>
                    </Space>
                    <div style={{ marginTop: 10 }}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        仅剩 {c.remaining_stock} 张 · 本人还可领 {Math.max(left, 0)} 张
                      </Typography.Text>
                    </div>
                  </Card>
                </Col>
              )
            })}
          </Row>
        )}
      </Card>

      <Modal
        open={!!claimed}
        onCancel={() => setClaimed(null)}
        footer={null}
        width={420}
        destroyOnClose
      >
        {claimed && (
          <Result
            status="success"
            title="领取成功"
            subTitle={`${claimed.coupon.campaign_name} · ${claimed.coupon.benefit_text}`}
            extra={[
              <div key="code" style={{ marginBottom: 16 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  券码（使用时向门店出示）
                </Typography.Text>
                <div style={{ marginTop: 6 }}>
                  <Typography.Text className="mono" strong copyable style={{ fontSize: 24 }}>
                    {claimed.coupon.code}
                  </Typography.Text>
                </div>
                <Typography.Text type="warning" style={{ fontSize: 12 }}>
                  有效期至 {new Date(claimed.coupon.expires_at).toLocaleString('zh-CN')}
                </Typography.Text>
              </div>,
              <Space key="actions">
                <Button onClick={() => setClaimed(null)}>继续逛逛</Button>
                <Button type="primary" onClick={() => navigate('/my-coupons')}>
                  查看我的优惠券
                </Button>
              </Space>,
            ]}
          />
        )}
      </Modal>
    </>
  )
}
