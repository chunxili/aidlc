/**
 * 风险标记审核。
 *
 * **这是必做页面而非可选**：它是三态决策中「人工审核」唯一的可见证据。
 * 缺了它，风控的三态在演示中会退化成两态（ADR-007）。
 *
 * 展开行显示完整判定理由 —— 运营看不到理由就无从审核（FR-052 AC-2）。
 */

import { Alert, Button, Card, Descriptions, Popconfirm, Segmented, Space, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { Paged, RiskEvent } from '../api/types'

const DECISION_TAG: Record<RiskEvent['decision'], { color: string; text: string }> = {
  PASS: { color: 'green', text: '放行' },
  BLOCK: { color: 'red', text: '拦截' },
  MANUAL_REVIEW: { color: 'orange', text: '人工审核' },
}

const STATUS_TAG: Record<RiskEvent['status'], { color: string; text: string }> = {
  PENDING: { color: 'orange', text: '待处理' },
  RELEASED: { color: 'green', text: '已解除' },
  KEPT: { color: 'red', text: '维持限制' },
}

const FILTERS = ['全部', 'PENDING', 'RELEASED', 'KEPT'] as const
const FILTER_LABEL: Record<string, string> = {
  全部: '全部',
  PENDING: '待处理',
  RELEASED: '已解除',
  KEPT: '维持限制',
}

export default function RiskPage() {
  const [data, setData] = useState<Paged<RiskEvent> | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<string>('PENDING')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const qs = filter === '全部' ? '' : `?status=${filter}`
      setData(await api.get<Paged<RiskEvent>>(`/api/risk/events${qs}`))
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    void load()
  }, [load])

  const handle = async (id: number, action: 'RELEASE' | 'KEEP') => {
    try {
      await api.post(`/api/risk/events/${id}/handle`, { action })
      message.success(action === 'RELEASE' ? '已解除限制，该用户可自行重新领取' : '已维持限制')
      void load()
    } catch (e) {
      message.error((e as ApiError).message)
    }
  }

  return (
    <Card
      title="风险标记审核"
      extra={
        <Segmented
          options={FILTERS.map((f) => ({ value: f, label: FILTER_LABEL[f] }))}
          value={filter}
          onChange={(v) => setFilter(v as string)}
        />
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="审核对象是用户身上的风险标记，不是待批的领取请求"
        description="被拦截的请求不占用库存、不创建券。解除限制后，用户走完全正常的领取路径重新领取，系统不代为补发。"
      />
      <Table
        rowKey="id"
        loading={loading}
        dataSource={data?.items ?? []}
        pagination={{ total: data?.total ?? 0, pageSize: data?.page_size ?? 20 }}
        expandable={{
          expandedRowRender: (r) => (
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="判定理由">{r.ai_reason}</Descriptions.Item>
              <Descriptions.Item label="判定来源">
                {r.decided_by === 'AI' ? 'AI 模型' : '规则引擎'}
                {r.degraded ? '（AI 不可用，已降级）' : ''}
              </Descriptions.Item>
              <Descriptions.Item label="窗口内请求数">{r.window_request_count}</Descriptions.Item>
              <Descriptions.Item label="关联活动">{r.campaign_id ?? '—'}</Descriptions.Item>
            </Descriptions>
          ),
        }}
        columns={[
          { title: '用户', dataIndex: 'username' },
          {
            title: '决策',
            dataIndex: 'decision',
            render: (v: RiskEvent['decision']) => (
              <Tag color={DECISION_TAG[v].color}>{DECISION_TAG[v].text}</Tag>
            ),
          },
          {
            title: '来源',
            dataIndex: 'decided_by',
            render: (v: RiskEvent['decided_by'], r) => (
              <Space size={4}>
                <Tag color={v === 'AI' ? 'purple' : 'blue'}>{v === 'AI' ? 'AI' : '规则'}</Tag>
                {r.degraded && <Tag color="orange">降级</Tag>}
              </Space>
            ),
          },
          { title: '评分', dataIndex: 'risk_score', render: (v: number | null) => v ?? '—' },
          { title: '窗口请求数', dataIndex: 'window_request_count' },
          {
            title: '状态',
            dataIndex: 'status',
            render: (v: RiskEvent['status']) => <Tag color={STATUS_TAG[v].color}>{STATUS_TAG[v].text}</Tag>,
          },
          {
            title: '时间',
            dataIndex: 'created_at',
            render: (v: string) => new Date(v).toLocaleString(),
          },
          {
            title: '处理人',
            dataIndex: 'handled_by',
            render: (v: string | null) => v ?? '—',
          },
          {
            title: '操作',
            render: (_, r) =>
              r.status === 'PENDING' ? (
                <Space>
                  <Popconfirm title="解除该用户的风险限制？" onConfirm={() => handle(r.id, 'RELEASE')}>
                    <Button size="small" type="primary">
                      解除
                    </Button>
                  </Popconfirm>
                  <Button size="small" danger onClick={() => handle(r.id, 'KEEP')}>
                    维持
                  </Button>
                </Space>
              ) : (
                <span>已处理</span>
              ),
          },
        ]}
      />
    </Card>
  )
}
