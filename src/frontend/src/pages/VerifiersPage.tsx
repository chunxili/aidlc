/** 核销人员名册（FR-067）。管理员查看全部门店的核销人员及其核销量。 */

import {
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Row,
  Select,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import dayjs from 'dayjs'
import { api } from '../api/client'
import { COUPON_TYPE_LABEL } from '../api/types'
import type { RedemptionRecord, Store, Verifier, VerifierRedemptions } from '../api/types'
import { PageHeader } from '../components/PageHeader'

const PAGE_SIZE = 10

/** 核销记录抽屉：管理员的动作是「看一眼这个人的记录再看下一个人」，
 *  用抽屉而非跳页，避免丢失名册的筛选与滚动位置。 */
function RedemptionDrawer({
  verifier,
  onClose,
}: {
  verifier: Verifier | null
  onClose: () => void
}) {
  const [data, setData] = useState<VerifierRedemptions | null>(null)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!verifier) {
      setData(null)
      setPage(1)
      return
    }
    setLoading(true)
    api
      .get<VerifierRedemptions>(
        `/api/admin/verifiers/${verifier.id}/redemptions?page=${page}&page_size=${PAGE_SIZE}`,
      )
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [verifier, page])

  // 切换人员时回到第一页，否则上一个人翻到第 3 页会让新打开的人显示空列表
  useEffect(() => {
    setPage(1)
  }, [verifier?.id])

  return (
    <Drawer
      open={!!verifier}
      onClose={onClose}
      width={860}
      title={verifier ? `${verifier.display_name} · 核销记录` : ''}
      destroyOnClose
    >
      {verifier && (
        <>
          <Descriptions size="small" column={2} bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label="姓名">{verifier.display_name}</Descriptions.Item>
            <Descriptions.Item label="账号">{verifier.username}</Descriptions.Item>
            <Descriptions.Item label="手机号">{verifier.phone ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="所属门店">
              <Tag>{verifier.store_district}</Tag>
              {verifier.store_name}
            </Descriptions.Item>
            <Descriptions.Item label="累计核销">
              {data?.total ?? verifier.redeemed_count} 张
            </Descriptions.Item>
            <Descriptions.Item label="账号状态">
              {verifier.status === 'ACTIVE' ? (
                <Tag color="green">已启用</Tag>
              ) : verifier.status === 'PENDING' ? (
                <Tag color="orange">待审核</Tag>
              ) : (
                <Tag color="red">已驳回</Tag>
              )}
            </Descriptions.Item>
          </Descriptions>

          <Table<RedemptionRecord>
            rowKey="id"
            size="small"
            loading={loading}
            dataSource={data?.items ?? []}
            pagination={{
              current: page,
              pageSize: PAGE_SIZE,
              total: data?.total ?? 0,
              onChange: setPage,
              showSizeChanger: false,
              showTotal: (t) => `共 ${t} 条`,
            }}
            locale={{
              emptyText: (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该核销人员暂无核销记录" />
              ),
            }}
            columns={[
              {
                title: '券码',
                dataIndex: 'code',
                width: 130,
                render: (v: string) => (
                  <Typography.Text copyable code style={{ fontSize: 12 }}>
                    {v}
                  </Typography.Text>
                ),
              },
              {
                title: '活动',
                width: 200,
                render: (_, r) => (
                  <div>
                    <div>{r.campaign_name}</div>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {COUPON_TYPE_LABEL[r.coupon_type]} · {r.benefit_text}
                    </Typography.Text>
                  </div>
                ),
              },
              {
                title: '订单金额',
                dataIndex: 'order_amount',
                width: 100,
                align: 'right',
                render: (v: string | null) => (v ? `¥${v}` : '—'),
              },
              {
                title: '优惠',
                dataIndex: 'discount_amount',
                width: 90,
                align: 'right',
                render: (v: string | null) =>
                  v ? <Typography.Text type="danger">-¥{v}</Typography.Text> : '—',
              },
              {
                title: '实付',
                dataIndex: 'payable_amount',
                width: 100,
                align: 'right',
                render: (v: string | null) =>
                  v ? <Typography.Text strong>¥{v}</Typography.Text> : '—',
              },
              {
                title: '核销时间',
                dataIndex: 'used_at',
                width: 150,
                render: (v: string) => (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {dayjs(v).format('YYYY-MM-DD HH:mm:ss')}
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

export default function VerifiersPage() {
  const [active, setActive] = useState<Verifier | null>(null)
  const [rows, setRows] = useState<Verifier[]>([])
  const [stores, setStores] = useState<Store[]>([])
  const [districts, setDistricts] = useState<string[]>([])
  const [district, setDistrict] = useState<string | undefined>()
  const [storeId, setStoreId] = useState<number | undefined>()
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<string[]>('/api/stores/districts').then(setDistricts).catch(() => setDistricts([]))
    api.get<Store[]>('/api/stores').then(setStores).catch(() => setStores([]))
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const qs = new URLSearchParams()
      if (district) qs.set('district', district)
      if (storeId) qs.set('store_id', String(storeId))
      const suffix = qs.toString() ? `?${qs}` : ''
      setRows(await api.get<Verifier[]>(`/api/admin/verifiers${suffix}`))
    } finally {
      setLoading(false)
    }
  }, [district, storeId])

  useEffect(() => {
    void load()
  }, [load])

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
      stores: new Set(rows.map((r) => r.store_id)).size,
      redeemed: rows.reduce((s, r) => s + r.redeemed_count, 0),
      pending: rows.filter((r) => r.status === 'PENDING').length,
    }),
    [rows],
  )

  const storeOptions = useMemo(
    () =>
      stores
        .filter((s) => !district || s.district === district)
        .map((s) => ({ value: s.id, label: `${s.name}（${s.code}）` })),
    [stores, district],
  )

  return (
    <>
      <PageHeader
        title="核销人员"
        description="全部门店的核销人员及其核销量，点击任意一行查看该人员的核销记录"
      />

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="核销人员" value={summary.people} suffix="人" />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="覆盖门店" value={summary.stores} suffix="家" />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="累计核销" value={summary.redeemed} suffix="张" />
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
          <Row gutter={8} style={{ width: 560 }}>
            <Col span={7}>
              <Select
                allowClear
                placeholder="行政区"
                style={{ width: '100%' }}
                value={district}
                onChange={(v) => {
                  setDistrict(v)
                  setStoreId(undefined)
                }}
                options={districts.map((d) => ({ value: d, label: d }))}
              />
            </Col>
            <Col span={10}>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="门店"
                style={{ width: '100%' }}
                value={storeId}
                onChange={setStoreId}
                options={storeOptions}
              />
            </Col>
            <Col span={7}>
              <Input.Search
                allowClear
                placeholder="姓名/账号/手机"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
            </Col>
          </Row>
        }
      >
        <Table
          rowKey="id"
          loading={loading}
          dataSource={shown}
          pagination={shown.length > 20 ? { pageSize: 20 } : false}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无核销人员" />,
          }}
          scroll={{ x: 900 }}
          onRow={(record) => ({
            style: { cursor: 'pointer' },
            onClick: () => setActive(record),
          })}
          columns={[
            {
              // 只呈现姓名：管理员在名册上关心的是「谁」，账号名是登录凭证而非身份标识，
              // 且两行结构使行高翻倍、屏幕上可见人数减半。账号名移入抽屉的人员信息区。
              title: '姓名',
              dataIndex: 'display_name',
              width: 120,
              fixed: 'left',
              render: (v: string) => <Typography.Text strong>{v}</Typography.Text>,
            },
            {
              title: '行政区',
              dataIndex: 'store_district',
              width: 100,
              render: (v: string) => <Tag>{v}</Tag>,
            },
            {
              title: '所属门店',
              width: 220,
              render: (_, r) => (
                <div>
                  <div>{r.store_name}</div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {r.store_code}
                  </Typography.Text>
                </div>
              ),
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
              render: (v: Verifier['status']) =>
                v === 'ACTIVE' ? (
                  <Tag color="green">已启用</Tag>
                ) : v === 'PENDING' ? (
                  <Tag color="orange">待审核</Tag>
                ) : (
                  <Tag color="red">已驳回</Tag>
                ),
            },
            {
              title: '累计核销',
              dataIndex: 'redeemed_count',
              width: 100,
              align: 'right',
              sorter: (a, b) => a.redeemed_count - b.redeemed_count,
              render: (v: number) => (
                <Typography.Text strong={v > 0}>{v}</Typography.Text>
              ),
            },
            {
              title: '入职时间',
              dataIndex: 'created_at',
              width: 120,
              render: (v: string) => (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {dayjs(v).format('YYYY-MM-DD')}
                </Typography.Text>
              ),
            },
            {
              // 整行可点，这一列是给「不知道行可以点」的人的显式入口
              title: '操作',
              width: 100,
              render: (_, r) => <Typography.Link onClick={() => setActive(r)}>核销记录</Typography.Link>,
            },
          ]}
        />
      </Card>

      <RedemptionDrawer verifier={active} onClose={() => setActive(null)} />
    </>
  )
}
