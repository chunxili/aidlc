/**
 * 活动管理。
 *
 * 表单要点：
 * - 有效时长用「数值 + 单位」输入，提交时统一换算为分钟：既照顾运营按天填写的习惯，
 *   也保留分钟粒度以支持 SC-003 现场演示（建 1 分钟有效期的活动）
 * - 编辑时面额与有效时长置灰：已领出券的 expires_at 已落库（ADR-003）
 * - 库存最小值绑定为当前值，前端即阻止调低（后端仍会校验）
 */

import {
  Alert,
  Button,
  Card,
  DatePicker,
  Drawer,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'
import dayjs from 'dayjs'
import { ApiError, api } from '../api/client'
import { CATEGORY_LABEL, ERROR_MESSAGE } from '../api/types'
import type { Campaign, Paged } from '../api/types'

const STATUS_TAG: Record<Campaign['status'], { color: string; text: string }> = {
  PENDING: { color: 'default', text: '未开始' },
  ACTIVE: { color: 'green', text: '进行中' },
  ENDED: { color: 'red', text: '已结束' },
}

const UNIT_MINUTES = { minute: 1, hour: 60, day: 1440 }

export default function CampaignsPage() {
  const [data, setData] = useState<Paged<Campaign> | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<Campaign | null>(null)
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await api.get<Paged<Campaign>>('/api/campaigns?page_size=50'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const openCreate = () => {
    setEditing(null)
    form.setFieldsValue({
      category: 'FOOD',
      face_value: 20,
      total_stock: 100,
      per_user_limit: 1,
      validity_value: 1,
      validity_unit: 'day',
      range: [dayjs(), dayjs().add(7, 'day')],
    })
    setOpen(true)
  }

  const openEdit = (c: Campaign) => {
    setEditing(c)
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
    <Card
      title="活动管理"
      extra={
        <Button type="primary" onClick={openCreate}>
          创建活动
        </Button>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="库存只能调高：调低会使已领取数超过总库存，破坏库存守恒。面额与有效时长在创建后不可修改。"
      />
      <Table
        rowKey="id"
        loading={loading}
        dataSource={data?.items ?? []}
        pagination={false}
        columns={[
          { title: '活动', dataIndex: 'name' },
          {
            title: '品类',
            dataIndex: 'category',
            render: (v: Campaign['category']) => <Tag>{CATEGORY_LABEL[v]}</Tag>,
          },
          { title: '面额', dataIndex: 'face_value', render: (v: string) => `¥${v}` },
          {
            title: '状态',
            dataIndex: 'status',
            render: (v: Campaign['status']) => (
              <Tooltip title="状态由起止时间实时派生，数据库中不存储该字段">
                <Tag color={STATUS_TAG[v].color}>{STATUS_TAG[v].text}</Tag>
              </Tooltip>
            ),
          },
          {
            title: '库存',
            render: (_, r) => `${r.claimed_count} / ${r.total_stock}（剩 ${r.remaining_stock}）`,
          },
          { title: '每人限领', dataIndex: 'per_user_limit' },
          {
            title: '领取后有效',
            dataIndex: 'validity_minutes',
            render: (v: number) =>
              v < 60 ? `${v} 分钟` : v < 1440 ? `${Math.round(v / 60)} 小时` : `${Math.round(v / 1440)} 天`,
          },
          {
            title: '结束时间',
            dataIndex: 'end_at',
            render: (v: string) => new Date(v).toLocaleString(),
          },
          {
            title: '操作',
            render: (_, r) => (
              <Button size="small" onClick={() => openEdit(r)}>
                编辑
              </Button>
            ),
          },
        ]}
      />

      <Drawer
        title={editing ? `编辑活动：${editing.name}` : '创建活动'}
        open={open}
        onClose={() => setOpen(false)}
        width={480}
        extra={
          <Button type="primary" onClick={submit}>
            提交
          </Button>
        }
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="活动名称" rules={[{ required: true }]}>
            <Input placeholder="例如 周末餐饮券" />
          </Form.Item>
          <Form.Item name="category" label="品类" rules={[{ required: true }]}
            extra="品类是 AI 生成推荐理由的语义来源，缺了它 AI 只能说面额大小">
            <Select
              options={Object.entries(CATEGORY_LABEL).map(([value, label]) => ({ value, label }))}
            />
          </Form.Item>

          {!editing && (
            <>
              <Form.Item name="face_value" label="面额（元）" rules={[{ required: true }]}>
                <InputNumber min={0.01} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="range" label="活动起止时间" rules={[{ required: true }]}>
                <DatePicker.RangePicker showTime style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item label="领取后有效时长" required
                extra="选「分钟」可现场演示「过期券核销」：建 1 分钟有效期的活动，领取后等 1 分钟即可">
                <Space.Compact style={{ width: '100%' }}>
                  <Form.Item name="validity_value" noStyle rules={[{ required: true }]}>
                    <InputNumber min={1} style={{ width: '60%' }} />
                  </Form.Item>
                  <Form.Item name="validity_unit" noStyle rules={[{ required: true }]}>
                    <Select
                      style={{ width: '40%' }}
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
          )}

          {editing && (
            <>
              <Form.Item label="面额（元）" extra="创建后不可修改">
                <InputNumber value={Number(editing.face_value)} disabled style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item label="领取后有效时长（分钟）"
                extra="创建后不可修改：已领出券的过期时间已落库，改动会使同一活动内的券遵循两套规则">
                <InputNumber value={editing.validity_minutes} disabled style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="end_at" label="结束时间" rules={[{ required: true }]}>
                <DatePicker showTime style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          <Form.Item
            name="total_stock"
            label="库存"
            rules={[{ required: true }]}
            extra={editing ? `只能调高，当前 ${editing.total_stock}` : undefined}
          >
            <InputNumber min={editing ? editing.total_stock : 1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="per_user_limit" label="每用户限领数" rules={[{ required: true }]}>
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
        <Typography.Text type="secondary">
          创建活动不会预生成任何券记录：券在用户领取那一刻才诞生。
        </Typography.Text>
      </Drawer>
    </Card>
  )
}
