/**
 * 领券广场。
 *
 * **推荐区位于领取动作之上**，这是 ADR-005 的可视化体现：用户先看到推荐与理由，
 * 再决定领取。竞赛演示步骤 b「领取成功含 AI 推荐理由」即由此满足 ——
 * 理由在页面上已存在，而非来自领券响应。
 */

import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Modal,
  Row,
  Skeleton,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
  notification,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../api/client'
import { CATEGORY_LABEL, ERROR_MESSAGE } from '../api/types'
import type { AvailableCampaign, ClaimResult, RecommendationResult } from '../api/types'

export default function CouponsPage() {
  const [recs, setRecs] = useState<RecommendationResult | null>(null)
  const [recLoading, setRecLoading] = useState(true)
  const [campaigns, setCampaigns] = useState<AvailableCampaign[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [claimed, setClaimed] = useState<ClaimResult | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setRecLoading(true)
    setError(null)
    try {
      const [r, c] = await Promise.all([
        api.get<RecommendationResult>('/api/recommendations?limit=5'),
        api.get<AvailableCampaign[]>('/api/campaigns/available'),
      ])
      setRecs(r)
      setCampaigns(c)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '加载失败')
    } finally {
      setLoading(false)
      setRecLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const claim = async (campaignId: number) => {
    try {
      const result = await api.post<ClaimResult>('/api/coupons/claim', { campaign_id: campaignId })
      setClaimed(result)
      void load()
    } catch (e) {
      if (!(e instanceof ApiError)) {
        message.error('领取失败')
        return
      }
      const text = ERROR_MESSAGE[e.code] ?? e.message
      // 风控两态用 notification：需要更长的阅读时间（frontend-design.md 第三节）
      if (e.code === 'RISK_BLOCKED' || e.code === 'RISK_MANUAL_REVIEW') {
        notification.warning({ message: '风控提示', description: text, duration: 8 })
      } else {
        message.warning(text)
      }
      void load()
    }
  }

  if (error) {
    return <Alert type="error" showIcon message={error} action={<Button onClick={load}>重试</Button>} />
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Card
        title={
          <Space>
            <span>{recs?.cold_start ? '新人推荐' : 'AI 智能推券'}</span>
            {recs?.degraded && (
              <Tooltip title={`AI 暂不可用（${recs.degrade_reason}），已降级为规则推荐。核心业务不受影响。`}>
                <Tag color="orange">规则推荐</Tag>
              </Tooltip>
            )}
          </Space>
        }
        extra={<Typography.Text type="secondary">推荐在领取之前生成，交易链路零 AI 依赖</Typography.Text>}
      >
        {recLoading ? (
          <Skeleton active paragraph={{ rows: 3 }} />
        ) : !recs?.items.length ? (
          <Empty description="暂无可推荐的活动" />
        ) : (
          <Row gutter={[16, 16]}>
            {recs.items.map((r) => (
              <Col key={r.campaign_id} xs={24} md={12} lg={8}>
                <Card
                  size="small"
                  title={r.campaign_name}
                  extra={<Tag color="geekblue">{CATEGORY_LABEL[r.category]}</Tag>}
                  actions={[
                    <Button key="claim" type="primary" onClick={() => claim(r.campaign_id)}>
                      领取
                    </Button>,
                  ]}
                >
                  <Statistic value={r.face_value} prefix="¥" valueStyle={{ fontSize: 22 }} />
                  <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                    {r.reason}
                  </Typography.Paragraph>
                  <Typography.Text type="secondary">剩余 {r.remaining_stock} 张</Typography.Text>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      <Card title="全部可领活动">
        <Table
          rowKey="id"
          loading={loading}
          dataSource={campaigns}
          locale={{ emptyText: <Empty description="暂无可领活动" /> }}
          columns={[
            { title: '活动', dataIndex: 'name' },
            {
              title: '品类',
              dataIndex: 'category',
              render: (v: AvailableCampaign['category']) => <Tag>{CATEGORY_LABEL[v]}</Tag>,
            },
            { title: '面额', dataIndex: 'face_value', render: (v: string) => `¥${v}` },
            { title: '剩余库存', dataIndex: 'remaining_stock' },
            {
              title: '剩余可领次数',
              render: (_, r) => `${r.per_user_limit - r.my_claimed_count} / ${r.per_user_limit}`,
            },
            {
              title: '领取后有效',
              dataIndex: 'validity_minutes',
              render: (v: number) => (v < 60 ? `${v} 分钟` : `${Math.round(v / 60)} 小时`),
            },
            {
              title: '操作',
              render: (_, r) => (
                <Button type="primary" size="small" onClick={() => claim(r.id)}>
                  领取
                </Button>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        open={!!claimed}
        onCancel={() => setClaimed(null)}
        onOk={() => setClaimed(null)}
        title="领取成功"
        okText="知道了"
        cancelButtonProps={{ style: { display: 'none' } }}
      >
        {claimed && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Typography.Text type="secondary">券码（核销时出示给核销人员）</Typography.Text>
            <Typography.Title level={2} copyable style={{ letterSpacing: 4, marginTop: 0 }}>
              {claimed.coupon.code}
            </Typography.Title>
            <Typography.Text>
              {claimed.coupon.campaign_name} · 面额 ¥{claimed.coupon.face_value}
            </Typography.Text>
            <Typography.Text type="warning">
              过期时间：{new Date(claimed.coupon.expires_at).toLocaleString()}
            </Typography.Text>
            <Typography.Text type="secondary">
              风控：{claimed.risk.decision} / 判定来源 {claimed.risk.decided_by}
              {claimed.risk.degraded ? '（AI 降级）' : ''}
            </Typography.Text>
          </Space>
        )}
      </Modal>
    </Space>
  )
}
