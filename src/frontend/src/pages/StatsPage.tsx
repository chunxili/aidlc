import {
  Card,
  Col,
  Progress,
  Row,
  Statistic,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Campaign, CampaignStats, Integrity, Overview, Paged } from '../api/types'
import { PageHeader } from '../components/PageHeader'

export default function StatsPage() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [rows, setRows] = useState<CampaignStats[]>([])
  const [integrity, setIntegrity] = useState<Integrity | null>(null)
  const [loading, setLoading] = useState(true)
  const [auto, setAuto] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const campaigns = await api.get<Paged<Campaign>>('/api/campaigns?page_size=50')
      setRows(
        await Promise.all(
          campaigns.items.map((c) => api.get<CampaignStats>(`/api/stats/campaigns/${c.id}`)),
        ),
      )
      // 全局汇总与数据校验仅管理员可读，运营访问本页时后端会拒绝
      try {
        const [o, i] = await Promise.all([
          api.get<Overview>('/api/stats/overview'),
          api.get<Integrity>('/api/stats/integrity'),
        ])
        setOverview(o)
        setIntegrity(i)
      } catch {
        setOverview(null)
        setIntegrity(null)
      }
      setUpdatedAt(new Date())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // 自动刷新：运营看板常驻大屏时需要，风控与领取数据会持续变化
  useEffect(() => {
    if (!auto) return
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [auto, load])

  const basis = rows[0]

  return (
    <>
      <PageHeader
        title="数据看板"
        description={
          updatedAt ? `数据更新于 ${updatedAt.toLocaleTimeString('zh-CN')}` : '正在加载数据'
        }
        extra={
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            自动刷新
            <Switch size="small" checked={auto} onChange={setAuto} style={{ marginLeft: 8 }} />
          </Typography.Text>
        }
      />

      {overview && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col xs={12} md={8} lg={4}>
            <Card size="small">
              <Statistic title="活动总数" value={overview.campaign_count} />
            </Card>
          </Col>
          <Col xs={12} md={8} lg={4}>
            <Card size="small">
              <Statistic title="投放库存" value={overview.total_stock} suffix="张" />
            </Card>
          </Col>
          <Col xs={12} md={8} lg={4}>
            <Card size="small">
              <Statistic title="累计领取" value={overview.claimed_count} suffix="张" />
            </Card>
          </Col>
          <Col xs={12} md={8} lg={4}>
            <Card size="small">
              <Statistic title="累计核销" value={overview.used_count} suffix="张" />
            </Card>
          </Col>
          <Col xs={12} md={8} lg={4}>
            <Card size="small">
              <Statistic
                title="近 24 小时拦截"
                value={overview.risk_blocked_24h}
                suffix="次"
                valueStyle={overview.risk_blocked_24h > 0 ? { color: '#c0362c' } : undefined}
              />
            </Card>
          </Col>
          <Col xs={12} md={8} lg={4}>
            <Card size="small">
              <Statistic
                title="待处理风险"
                value={overview.risk_pending_count}
                suffix="条"
                valueStyle={overview.risk_pending_count > 0 ? { color: '#b7791f' } : undefined}
              />
            </Card>
          </Col>
        </Row>
      )}

      <Card
        title="活动效果"
        style={{ marginBottom: 16 }}
        extra={
          integrity ? (
            <Tooltip
              title={
                integrity.ok
                  ? '库存与券数校验一致'
                  : `存在异常：超发 ${integrity.inv1_stock_overflow_count} 个活动`
              }
            >
              <Tag color={integrity.ok ? 'green' : 'red'}>
                {integrity.ok ? '数据校验正常' : '数据校验异常'}
              </Tag>
            </Tooltip>
          ) : null
        }
      >
        <Table
          rowKey="campaign_id"
          loading={loading}
          dataSource={rows}
          pagination={false}
          scroll={{ x: 900 }}
          columns={[
            {
              title: '活动名称',
              dataIndex: 'campaign_name',
              fixed: 'left',
              width: 200,
              ellipsis: true,
            },
            { title: '投放', dataIndex: 'total_stock', width: 80, align: 'right' },
            { title: '已领取', dataIndex: 'claimed_count', width: 90, align: 'right' },
            { title: '剩余', dataIndex: 'remaining_stock', width: 80, align: 'right' },
            {
              title: (
                <Tooltip title={basis?.claim_rate_basis}>
                  <span style={{ borderBottom: '1px dotted #b3bac7' }}>领取率</span>
                </Tooltip>
              ),
              dataIndex: 'claim_rate',
              width: 150,
              render: (v: number) => (
                <Progress
                  percent={Number((v * 100).toFixed(1))}
                  size="small"
                  strokeColor="#1b4b91"
                />
              ),
            },
            {
              title: (
                <Tooltip title={basis?.redeem_rate_basis}>
                  <span style={{ borderBottom: '1px dotted #b3bac7' }}>核销率</span>
                </Tooltip>
              ),
              dataIndex: 'redeem_rate',
              width: 150,
              render: (v: number | null) =>
                v === null ? (
                  <Typography.Text type="secondary">—</Typography.Text>
                ) : (
                  <Progress
                    percent={Number((v * 100).toFixed(1))}
                    size="small"
                    strokeColor="#0f7b55"
                  />
                ),
            },
            { title: '已核销', dataIndex: 'used_count', width: 90, align: 'right' },
            { title: '待使用', dataIndex: 'active_count', width: 90, align: 'right' },
            {
              title: '已过期',
              dataIndex: 'expired_count',
              width: 90,
              align: 'right',
              render: (v: number) => (
                <Typography.Text type={v > 0 ? 'warning' : undefined}>{v}</Typography.Text>
              ),
            },
          ]}
        />
        {basis && (
          <Typography.Paragraph type="secondary" style={{ margin: '12px 0 0', fontSize: 12 }}>
            领取率 = 已领取 / 投放库存；核销率 = 已核销 / 已领取
          </Typography.Paragraph>
        )}
      </Card>
    </>
  )
}
