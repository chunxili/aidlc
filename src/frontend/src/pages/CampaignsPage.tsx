import {
  Button,
  Card,
  DatePicker,
  Drawer,
  Form,
  Input,
  InputNumber,
  Progress,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  App as AntApp,
} from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import dayjs from 'dayjs'
import { ApiError, api } from '../api/client'
import { CATEGORY_LABEL, ERROR_MESSAGE } from '../api/types'
import type { Campaign, CampaignStatus, Paged } from '../api/types'
import { PageHeader } from '../components/PageHeader'

const STATUS: Record<CampaignStatus, { color: string; text: string }> = {
  PENDING: { color: 'default', text: '未开始' },
  ACTIVE: { color: 'green', text: '进行中' },
  ENDED: { color: 'red', text: '已结束' },
}

const UNIT_MINUTES = { minute: 1, hour: 60, day: 1440 }
const FILTERS = ['全部', 'ACTIVE', 'PENDING', 'ENDED'] as const

export default function CampaignsPage() {
  const { message } = AntApp.useApp()
  const [data, setData] = useState<Paged<Campaign> | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<Campaign | null>(null)
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('全部')
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await api.get<Paged<Campaign>>('/api/campaigns?page_size=100'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const rows = useMemo(() => {
    const items = data?.items ?? []
    return filter === '全部' ? items : items.filter((c) => c.status === filter)
  }, [data, filter])

  const summary = useMemo(() => {
    const items = data?.items ?? []
    return {
      active: items.filter((c) => c.status === 'ACTIVE').length,
      stock: items.reduce((s, c) => s + c.total_stock, 0),
      claimed: items.reduce((s, c) => s + c.claimed_count, 0),
    }
  }, [data])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({
      category: 'FOOD',
      face_value: 20,
      total_stock: 100,
      per_user_limit: 1,
      validity_value: 7,
      validity_unit: 'day',
      range: [dayjs(), dayjs().add(7, 'day')],
    })
    setOpen(true)
  }

  const openEdit = (c: Campaign) => {
    setEditing(c)
    form.resetFields()
    form.setFieldsValue({
      name: c.name,
      category: c.category,
      total_stock: c.total_stock,
      per_user_limit: c.per_user_limit,
      end_at: dayjs(c.end_at),
    })
    setOpen(true)
  }

  const submit = async () => {
    const v = await form.validateFields()
    try {
      if (editing) {
        await api.patch(`/api/campaigns/${editing.id}`, {
          name: v.name,
          category: v.category,
          total_stock: v.total_stock,
          per_user_limit: v.per_user_limit,
          end_at: (v.end_at as dayjs.Dayjs).toISOString(),
        })
        message.success('活动已更新')
      } else {
        const [start, end] = v.range as [dayjs.Dayjs, dayjs.Dayjs]
        await api.post('/api/campaigns', {
          name: v.name,
          category: v.category,
          face_value: String(v.face_value),
          total_stock: v.total_stock,
          start_at: start.toISOString(),
          end_at: end.toISOString(),
          validity_minutes:
            v.validity_value * UNIT_MINUTES[v.validity_unit as keyof typeof UNIT_MINUTES],
          per_user_limit: v.per_user_limit,
        })
        message.success('活动已创建')
      }
      setOpen(false)
      void load()
    } catch (e) {
      const err = e as ApiError
      message.error(ERROR_MESSAGE[err.code] ?? err.message)
    }
  }

  return (
    <>
      <PageHeader
        title="活动管理"
        description={`进行中 ${summary.active} 个 · 累计投放 ${summary.stock} 张 · 已领取 ${summary.claimed} 张`}
        extra={
          <Button type="primary" onClick={openCreate}>
            创建活动
          </Button>
        }
      />

      <Card
        extra={
          <Segmented
            size="small"
            value={filter}
            onChange={(v) => setFilter(v as never)}
            options={FILTERS.map((f) => ({
              value: f,
              label: f === '全部' ? '全部' : STATUS[f as CampaignStatus].text,
            }))}
          />
        }
      >
        <Table
          rowKey="id"
          loading={loading}
          dataSource={rows}
          pagination={false}
          scroll={{ x: 1020 }}
          columns={[
            {
              title: '活动名称',
              dataIndex: 'name',
              fixed: 'left',
              width: 200,
              ellipsis: true,
              render: (v: string, r) => (
                <div>
                  <Typography.Text strong>{v}</Typography.Text>
                  <div>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {CATEGORY_LABEL[r.category]} · 每人限领 {r.per_user_limit} 张
                    </Typography.Text>
                  </div>
                </div>
              ),
            },
            {
              title: '面额',
              dataIndex: 'face_value',
              width: 90,
              align: 'right',
              render: (v: string) => <Typography.Text strong>¥{Number(v)}</Typography.Text>,
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 90,
              render: (v: CampaignStatus) => <Tag color={STATUS[v].color}>{STATUS[v].text}</Tag>,
            },
            {
              title: '领取进度',
              width: 200,
              render: (_, r) => (
                <div>
                  <Progress
                    percent={Math.round((r.claimed_count / r.total_stock) * 100)}
                    size="small"
                    strokeColor="#1b4b91"
                  />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {r.claimed_count} / {r.total_stock} 张，剩 {r.remaining_stock}
                  </Typography.Text>
                </div>
              ),
            },
            {
              title: '领取后有效期',
              dataIndex: 'validity_minutes',
              width: 120,
              render: (v: number) =>
                v < 60 ? `${v} 分钟` : v < 1440 ? `${Math.round(v / 60)} 小时` : `${Math.round(v / 1440)} 天`,
            },
            {
              title: '活动时间',
              width: 190,
              render: (_, r) => (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {dayjs(r.start_at).format('MM-DD HH:mm')} 至 {dayjs(r.end_at).format('MM-DD HH:mm')}
                </Typography.Text>
              ),
            },
            {
              title: '操作',
              width: 80,
              fixed: 'right',
              render: (_, r) => (
                <Typography.Link onClick={() => openEdit(r)}>编辑</Typography.Link>
              ),
            },
          ]}
        />
      </Card>

      <Drawer
        title={editing ? '编辑活动' : '创建活动'}
        open={open}
        onClose={() => setOpen(false)}
        width={460}
        footer={
          <Space style={{ float: 'right' }}>
            <Button onClick={() => setOpen(false)}>取消</Button>
            <Button type="primary" onClick={submit}>
              保存
            </Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item name="name" label="活动名称" rules={[{ required: true, message: '请输入活动名称' }]}>
            <Input placeholder="例如：周末餐饮满减" />
          </Form.Item>
          <Form.Item name="category" label="优惠品类" rules={[{ required: true }]}>
            <Select
              options={Object.entries(CATEGORY_LABEL).map(([value, label]) => ({ value, label }))}
            />
          </Form.Item>

          {!editing ? (
            <>
              <Form.Item name="face_value" label="面额（元）" rules={[{ required: true }]}>
                <InputNumber min={0.01} precision={2} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="range" label="活动起止时间" rules={[{ required: true }]}>
                <DatePicker.RangePicker showTime style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item label="领取后有效期" required>
                <Space.Compact style={{ width: '100%' }}>
                  <Form.Item name="validity_value" noStyle rules={[{ required: true }]}>
                    <InputNumber min={1} style={{ width: '62%' }} />
                  </Form.Item>
                  <Form.Item name="validity_unit" noStyle rules={[{ required: true }]}>
                    <Select
                      style={{ width: '38%' }}
                      options={[
                        { value: 'minute', label: '分钟' },
                        { value: 'hour', label: '小时' },
                        { value: 'day', label: '天' },
                      ]}
                    />
                  </Form.Item>
                </Space.Compact>
              </Form.Item>
            </>
          ) : (
            <>
              <Form.Item label="面额（元）">
                <InputNumber value={Number(editing.face_value)} disabled style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item label="领取后有效期（分钟）">
                <InputNumber value={editing.validity_minutes} disabled style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="end_at" label="结束时间" rules={[{ required: true }]}>
                <DatePicker showTime style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          <Form.Item
            name="total_stock"
            label="投放库存"
            rules={[{ required: true }]}
            extra={editing ? '库存仅支持追加' : undefined}
          >
            <InputNumber min={editing ? editing.total_stock : 1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="per_user_limit" label="每人限领" rules={[{ required: true }]}>
            <InputNumber min={1} style={{ width: '100%' }} addonAfter="张" />
          </Form.Item>
        </Form>
      </Drawer>
    </>
  )
}
