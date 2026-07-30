/** 运营人员名册（FR-069 + FR-071）。
 *
 *  管理员看运营人员，关心的不是账号资料而是这个人干了多少活、效果如何，
 *  所以列的是投放业绩而非「账号/手机/创建时间」的翻版。
 *  点击任意一行下钻到该运营发布的活动列表。
 */

import {
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Progress,
  Row,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import dayjs from 'dayjs'
import { api } from '../api/client'
import { CATEGORY_LABEL, COUPON_TYPE_LABEL } from '../api/types'
import type {
  AccountStatus,
  CampaignStatus,
  Operator,
  OperatorCampaign,
  OperatorCampaigns,
} from '../api/types'
import { PageHeader } from '../components/PageHeader'

const PAGE_SIZE = 10

const STATUS_TAG: Record<AccountStatus, { color: string; label: string }> = {
  ACTIVE: { color: 'green', label: '已启用' },
  PENDING: { color: 'orange', label: '待审核' },
  REJECTED: { color: 'red', label: '已驳回' },
}

const CAMPAIGN_STATUS_TAG: Record<CampaignStatus, { color: string; label: string }> = {
  PENDING: { color: 'default', label: '未开始' },
  ACTIVE: { color: 'green', label: '进行中' },
  ENDED: { color: 'default', label: '已结束' },
}

/** 核销率。分母为 0 时显示「—」而不是 0%：无人领取与领了没人用是两回事 */
function RateText({ value }: { value: number | null }) {
  if (value === null) return <Typography.Text type="secondary">—</Typography.Text>
  return <Typography.Text strong={value > 0}>{(value * 100).toFixed(1)}%</Typography.Text>
}

/** 发布活动抽屉。界面文案用「发布的券」，列头以投放/已领取/已核销体现其为活动粒度 */
function CampaignDrawer({
  operator,
  onClose,
}: {
  operator: Operator | null
  onClose: () => void
}) {
  const [data, setData] = useState<OperatorCampaigns | null>(null)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!operator) {
      setData(null)
      return
    }
    setLoading(true)
    api
      .get<OperatorCampaigns>(
        `/api/admin/operators/${operator.id}/campaigns?page=${page}&page_size=${PAGE_SIZE}`,
      )
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [operator, page])

  // 切换人员时回到第一页，否则上一个人翻到第 3 页会让新打开的人显示空列表
  useEffect(() => {
    setPage(1)
  }, [operator?.id])

  return (
    <Drawer
      open={!!operator}
      onClose={onClose}
      width={900}
      title={operator ? `${operator.display_name} · 发布的券` : ''}
      destroyOnClose
    >
      {operator && (
        <>
          <Descriptions size="small" column={2} bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label="姓名">{operator.display_name}</Descriptions.Item>
            <Descriptions.Item label="账号">{operator.username}</Descriptions.Item>
            <Descriptions.Item label="手机号">{operator.phone ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="账号状态">
              <Tag color={STATUS_TAG[operator.status].color}>
                {STATUS_TAG[operator.status].label}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="发布活动">{operator.campaign_count} 个</Descriptions.Item>
            <Descriptions.Item label="投放总量">{operator.total_stock} 张</Descriptions.Item>
            <Descriptions.Item label="已领取">{operator.claimed_count} 张</Descriptions.Item>
            <Descriptions.Item label="已核销">
              {operator.used_count} 张（核销率 <RateText value={operator.redeem_rate} />）
            </Descriptions.Item>
          </Descriptions>

          <Table<OperatorCampaign>
            rowKey="id"
            size="small"
            loading={loading}
            dataSource={data?.items ?? []}
            scroll={{ x: 820 }}
            pagination={{
              current: page,
              pageSize: PAGE_SIZE,
              total: data?.total ?? 0,
              onChange: setPage,
              showSizeChanger: false,
              showTotal: (t) => `共 ${t} 个活动`,
            }}
            locale={{
              emptyText: (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该运营人员尚未发布活动" />
              ),
            }}
            columns={[
              {
                title: '活动',
                width: 220,
                fixed: 'left',
                render: (_, r) => (
                  <div>
                    <Typography.Text strong>{r.name}</Typography.Text>
                    <div>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {CATEGORY_LABEL[r.category]} · {COUPON_TYPE_LABEL[r.coupon_type]}
                      </Typography.Text>
                    </div>
                  </div>
                ),
              },
              { title: '优惠', dataIndex: 'benefit_text', width: 190 },
              { title: '投放', dataIndex: 'total_stock', width: 80, align: 'right' },
              { title: '已领取', dataIndex: 'claimed_count', width: 80, align: 'right' },
              {
                title: '已核销',
                dataIndex: 'used_count',
                width: 80,
                align: 'right',
                render: (v: number) => <Typography.Text strong={v > 0}>{v}</Typography.Text>,
              },
              {
                title: '状态',
                dataIndex: 'status',
                width: 90,
                render: (v: CampaignStatus) => (
                  <Tag color={CAMPAIGN_STATUS_TAG[v].color}>{CAMPAIGN_STATUS_TAG[v].label}</Tag>
                ),
              },
              {
                title: '活动时间',
                width: 170,
                render: (_, r) => (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {dayjs(r.start_at).format('MM-DD HH:mm')} ~{' '}
                    {dayjs(r.end_at).format('MM-DD HH:mm')}
                  </Typography.Text>
                ),
              },
            ]}
          />
        </>
      )}
    </Drawer>
  )
}

export default function OperatorsPage() {
  const [rows, setRows] = useState<Operator[]>([])
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(true)
  const [active, setActive] = useState<Operator | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await api.get<Operator[]>('/api/admin/operators'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // 名册规模在百量级，关键字在前端过滤即可，无需为此加一个后端查询参数
  const shown = useMemo(() => {
    const k = keyword.trim().toLowerCase()
    if (!k) return rows
    return rows.filter(
      (r) =>
        r.display_name.toLowerCase().includes(k) ||
        r.username.toLowerCase().includes(k) ||
        (r.phone ?? '').includes(k),
    )
  }, [rows, keyword])

  const summary = useMemo(
    () => ({
      people: rows.length,
      campaigns: rows.reduce((s, r) => s + r.campaign_count, 0),
      stock: rows.reduce((s, r) => s + r.total_stock, 0),
      used: rows.reduce((s, r) => s + r.used_count, 0),
      pending: rows.filter((r) => r.status === 'PENDING').length,
    }),
    [rows],
  )

  return (
    <>
      <PageHeader
        title="运营人员"
        description="全部运营人员及其投放业绩，点击任意一行查看该人员发布的券"
      />

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="运营人员" value={summary.people} suffix="人" />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="发布活动" value={summary.campaigns} suffix="个" />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="投放总量" value={summary.stock} suffix="张" />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="待审核"
              value={summary.pending}
              suffix="人"
              valueStyle={summary.pending > 0 ? { color: '#b7791f' } : undefined}
            />
          </Card>
        </Col>
      </Row>

      <Card
        extra={
          <Input.Search
            allowClear
            style={{ width: 240 }}
            placeholder="姓名/账号/手机"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
        }
      >
        <Table<Operator>
          rowKey="id"
          loading={loading}
          dataSource={shown}
          pagination={shown.length > 20 ? { pageSize: 20 } : false}
          scroll={{ x: 980 }}
          onRow={(record) => ({
            style: { cursor: 'pointer' },
            onClick: () => setActive(record),
          })}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无运营人员" />,
          }}
          columns={[
            {
              title: '姓名',
              dataIndex: 'display_name',
              width: 120,
              fixed: 'left',
              render: (v: string) => <Typography.Text strong>{v}</Typography.Text>,
            },
            {
              title: '手机号',
              dataIndex: 'phone',
              width: 130,
              render: (v: string | null) => v ?? '—',
            },
            {
              title: '账号状态',
              dataIndex: 'status',
              width: 100,
              render: (v: AccountStatus) => (
                <Tag color={STATUS_TAG[v].color}>{STATUS_TAG[v].label}</Tag>
              ),
            },
            {
              title: '发布活动',
              dataIndex: 'campaign_count',
              width: 100,
              align: 'right',
              sorter: (a, b) => a.campaign_count - b.campaign_count,
            },
            {
              title: '投放总量',
              dataIndex: 'total_stock',
              width: 100,
              align: 'right',
              sorter: (a, b) => a.total_stock - b.total_stock,
            },
            {
              title: '已领取',
              dataIndex: 'claimed_count',
              width: 100,
              align: 'right',
              render: (v: number, r) => (
                <div>
                  <div>{v}</div>
                  {r.total_stock > 0 && (
                    <Progress
                      percent={Math.round((v / r.total_stock) * 100)}
                      size="small"
                      showInfo={false}
                    />
                  )}
                </div>
              ),
            },
            {
              title: '已核销',
              dataIndex: 'used_count',
              width: 90,
              align: 'right',
              sorter: (a, b) => a.used_count - b.used_count,
              render: (v: number) => <Typography.Text strong={v > 0}>{v}</Typography.Text>,
            },
            {
              title: '核销率',
              dataIndex: 'redeem_rate',
              width: 90,
              align: 'right',
              render: (v: number | null) => <RateText value={v} />,
            },
            {
              title: '加入时间',
              dataIndex: 'created_at',
              width: 110,
              render: (v: string) => (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {dayjs(v).format('YYYY-MM-DD')}
                </Typography.Text>
              ),
            },
            {
              title: '操作',
              width: 110,
              render: (_, r) => (
                <Typography.Link onClick={() => setActive(r)}>发布的券</Typography.Link>
              ),
            },
          ]}
        />
      </Card>

      <CampaignDrawer operator={active} onClose={() => setActive(null)} />
    </>
  )
}
