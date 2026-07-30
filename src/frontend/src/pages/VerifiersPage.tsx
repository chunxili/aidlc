/** 核销人员名册（FR-067）。管理员查看全部门店的核销人员及其核销量。 */

import { Card, Col, Empty, Input, Row, Select, Statistic, Table, Tag, Typography } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import dayjs from 'dayjs'
import { api } from '../api/client'
import type { Store, Verifier } from '../api/types'
import { PageHeader } from '../components/PageHeader'

export default function VerifiersPage() {
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
      <PageHeader title="核销人员" description="全部门店的核销人员及其核销量" />

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
          columns={[
            {
              title: '姓名',
              width: 160,
              fixed: 'left',
              render: (_, r) => (
                <div>
                  <Typography.Text strong>{r.display_name}</Typography.Text>
                  <div>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {r.username}
                    </Typography.Text>
                  </div>
                </div>
              ),
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
          ]}
        />
      </Card>
    </>
  )
}
