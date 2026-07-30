import {
  Card,
  Descriptions,
  Empty,
  Popconfirm,
  Segmented,
  Space,
  Table,
  Tag,
  Typography,
  App as AntApp,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'
import dayjs from 'dayjs'
import { ApiError, api } from '../api/client'
import type { Paged, RiskEvent } from '../api/types'
import { PageHeader } from '../components/PageHeader'

const DECISION: Record<RiskEvent['decision'], { color: string; text: string }> = {
  PASS: { color: 'green', text: '放行' },
  BLOCK: { color: 'red', text: '已拦截' },
  MANUAL_REVIEW: { color: 'orange', text: '待人工复核' },
}

const STATUS: Record<RiskEvent['status'], { color: string; text: string }> = {
  PENDING: { color: 'orange', text: '待处理' },
  RELEASED: { color: 'green', text: '已解除' },
  KEPT: { color: 'red', text: '维持限制' },
}

const FILTERS = ['PENDING', 'RELEASED', 'KEPT', '全部'] as const
const FILTER_LABEL: Record<string, string> = {
  PENDING: '待处理',
  RELEASED: '已解除',
  KEPT: '维持限制',
  全部: '全部',
}

export default function RiskPage({ onHandled }: { onHandled?: () => void }) {
  const { message } = AntApp.useApp()
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
      message.success(action === 'RELEASE' ? '已解除限制' : '已维持限制')
      void load()
      onHandled?.()
    } catch (e) {
      message.error((e as ApiError).message)
    }
  }

  return (
    <>
      <PageHeader
        title="风险名单"
        description="系统识别到异常领取行为的会员，解除限制后会员可继续领取"
      />

      <Card
        extra={
          <Segmented
            size="small"
            options={FILTERS.map((f) => ({ value: f, label: FILTER_LABEL[f] }))}
            value={filter}
            onChange={(v) => setFilter(v as string)}
          />
        }
      >
        <Table
          rowKey="id"
          loading={loading}
          dataSource={data?.items ?? []}
          locale={{
            emptyText: (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无风险记录" />
            ),
          }}
          pagination={data && data.total > 20 ? { total: data.total, pageSize: 20 } : false}
          expandable={{
            expandedRowRender: (r) => (
              <Descriptions column={2} size="small" bordered style={{ maxWidth: 900 }}>
                <Descriptions.Item label="判定说明" span={2}>
                  {r.ai_reason}
                </Descriptions.Item>
                <Descriptions.Item label="窗口内请求次数">{r.window_request_count}</Descriptions.Item>
                <Descriptions.Item label="风险评分">{r.risk_score ?? '—'}</Descriptions.Item>
                <Descriptions.Item label="判定方式">
                  {r.decided_by === 'AI' ? '模型判定' : '规则判定'}
                  {r.degraded ? '（模型不可用，已回退规则）' : ''}
                </Descriptions.Item>
                <Descriptions.Item label="关联活动">{r.campaign_id ?? '—'}</Descriptions.Item>
              </Descriptions>
            ),
          }}
          columns={[
            {
              title: '会员',
              dataIndex: 'username',
              width: 130,
              render: (v: string) => <Typography.Text strong>{v}</Typography.Text>,
            },
            {
              title: '处置结果',
              dataIndex: 'decision',
              width: 120,
              render: (v: RiskEvent['decision']) => (
                <Tag color={DECISION[v].color}>{DECISION[v].text}</Tag>
              ),
            },
            {
              title: '判定方式',
              dataIndex: 'decided_by',
              width: 130,
              render: (v: RiskEvent['decided_by'], r) => (
                <Space size={4}>
                  <Tag color={v === 'AI' ? 'purple' : 'blue'}>{v === 'AI' ? '模型' : '规则'}</Tag>
                  {r.degraded && <Tag>回退</Tag>}
                </Space>
              ),
            },
            {
              title: '评分',
              dataIndex: 'risk_score',
              width: 70,
              align: 'right',
              render: (v: number | null) => v ?? '—',
            },
            { title: '请求次数', dataIndex: 'window_request_count', width: 90, align: 'right' },
            {
              title: '状态',
              dataIndex: 'status',
              width: 100,
              render: (v: RiskEvent['status']) => <Tag color={STATUS[v].color}>{STATUS[v].text}</Tag>,
            },
            {
              title: '触发时间',
              dataIndex: 'created_at',
              width: 160,
              render: (v: string) => (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {dayjs(v).format('MM-DD HH:mm:ss')}
                </Typography.Text>
              ),
            },
            {
              title: '处理人',
              dataIndex: 'handled_by',
              width: 100,
              render: (v: string | null) => v ?? '—',
            },
            {
              title: '操作',
              width: 140,
              fixed: 'right',
              render: (_, r) =>
                r.status === 'PENDING' ? (
                  <Space>
                    <Popconfirm
                      title="解除限制"
                      description="解除后该会员可继续领取优惠券"
                      onConfirm={() => handle(r.id, 'RELEASE')}
                    >
                      <Typography.Link>解除</Typography.Link>
                    </Popconfirm>
                    <Popconfirm title="维持限制" onConfirm={() => handle(r.id, 'KEEP')}>
                      <Typography.Link type="danger">维持</Typography.Link>
                    </Popconfirm>
                  </Space>
                ) : (
                  <Typography.Text type="secondary">已处理</Typography.Text>
                ),
            },
          ]}
          scroll={{ x: 1080 }}
        />
      </Card>
    </>
  )
}
