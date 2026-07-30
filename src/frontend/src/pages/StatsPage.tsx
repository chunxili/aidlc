/**
 * 统计面板。三层：全局卡片 → 活动明细 → 对账区。
 *
 * 两个比率旁的口径说明**直接取后端返回的 *_basis 字段**，不在前端硬编码，
 * 避免前后端口径漂移（FR-030 AC-4）。
 *
 * 对账区把「库存守恒」从文档里的一句话变成可点击的证据（NFR-009）。
 */

import { Alert, Button, Card, Col, Result, Row, Statistic, Table, Tooltip, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Campaign, CampaignStats, Integrity, Overview, Paged } from '../api/types'

export default function StatsPage() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [rows, setRows] = useState<CampaignStats[]>([])
  const [integrity, setIntegrity] = useState<Integrity | null>(null)
  const [loading, setLoading] = useState(true)
  const [adminOnlyError, setAdminOnlyError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const campaigns = await api.get<Paged<Campaign>>('/api/campaigns?page_size=50')
      const stats = await Promise.all(
        campaigns.items.map((c) => api.get<CampaignStats>(`/api/stats/campaigns/${c.id}`)),
      )
      setRows(stats)
      // overview 与 integrity 仅 ADMIN 可读；OPERATOR 打开本页时会 403
      try {
        const [o, i] = await Promise.all([
          api.get<Overview>('/api/stats/overview'),
          api.get<Integrity>('/api/stats/integrity'),
        ])
        setOverview(o)
        setIntegrity(i)
      } catch {
        setAdminOnlyError(true)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const basis = rows[0]

  return (
    <div>
      {adminOnlyError && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="全局汇总与对账区仅管理员可见"
          description="后端对越权请求返回 403，前端不做绕过。"
        />
      )}

      {overview && (
        <Card title="全局概览" style={{ marginBottom: 16 }} extra={<Button onClick={load}>刷新</Button>}>
          <Row gutter={16}>
            <Col xs={12} md={4}>
              <Statistic title="活动数" value={overview.campaign_count} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="总库存" value={overview.total_stock} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="总领取" value={overview.claimed_count} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="总核销" value={overview.used_count} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic
                title="近 24h 风控拦截"
                value={overview.risk_blocked_24h}
                valueStyle={{ color: overview.risk_blocked_24h > 0 ? '#cf1322' : undefined }}
              />
            </Col>
            <Col xs={12} md={4}>
              <Statistic
                title="待处理风险标记"
                value={overview.risk_pending_count}
                valueStyle={{ color: overview.risk_pending_count > 0 ? '#d46b08' : undefined }}
              />
            </Col>
          </Row>
        </Card>
      )}

      <Card title="活动明细" style={{ marginBottom: 16 }}>
        <Table
          rowKey="campaign_id"
          loading={loading}
          dataSource={rows}
          pagination={false}
          columns={[
            { title: '活动', dataIndex: 'campaign_name' },
            { title: '总库存', dataIndex: 'total_stock' },
            { title: '已领取', dataIndex: 'claimed_count' },
            { title: '剩余库存', dataIndex: 'remaining_stock' },
            {
              title: (
                <Tooltip title={basis?.claim_rate_basis}>
                  <span style={{ borderBottom: '1px dashed #999' }}>领取率</span>
                </Tooltip>
              ),
              dataIndex: 'claim_rate',
              render: (v: number) => `${(v * 100).toFixed(1)}%`,
            },
            {
              title: (
                <Tooltip title={basis?.redeem_rate_basis}>
                  <span style={{ borderBottom: '1px dashed #999' }}>核销率</span>
                </Tooltip>
              ),
              dataIndex: 'redeem_rate',
              // claimed_count=0 时后端返回 null，此处显示「—」而非 0
              render: (v: number | null) => (v === null ? '—' : `${(v * 100).toFixed(1)}%`),
            },
            { title: '已核销', dataIndex: 'used_count' },
            { title: '未核销未过期', dataIndex: 'active_count' },
            { title: '未核销已过期', dataIndex: 'expired_count' },
          ]}
        />
        {basis && (
          <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
            口径：领取率 —— {basis.claim_rate_basis}；核销率 —— {basis.redeem_rate_basis}
          </Typography.Paragraph>
        )}
      </Card>

      {integrity && (
        <Card title="对账自检">
          <Result
            status={integrity.ok ? 'success' : 'error'}
            title={integrity.ok ? '两条不变量均成立' : '发现数据不一致'}
            subTitle={
              <div>
                <div>INV-1 库存守恒：超发活动数 = {integrity.inv1_stock_overflow_count}</div>
                <div>
                  INV-2 券的完全划分：不一致活动 ={' '}
                  {integrity.inv2_mismatch_campaign_ids.length
                    ? integrity.inv2_mismatch_campaign_ids.join(', ')
                    : '无'}
                </div>
              </div>
            }
            extra={<Button onClick={load}>重新校验</Button>}
          />
        </Card>
      )}
    </div>
  )
}
