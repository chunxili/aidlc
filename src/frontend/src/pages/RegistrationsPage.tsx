/** 注册审核（FR-066）。管理员审批核销人员与运营人员的账号申请。 */

import { Card, Empty, Input, Modal, Space, Table, Tag, Typography, App as AntApp } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import dayjs from 'dayjs'
import { ApiError, api } from '../api/client'
import { ROLE_LABEL } from '../api/types'
import type { PendingUser, Role } from '../api/types'
import { PageHeader } from '../components/PageHeader'

const ROLE_COLOR: Partial<Record<Role, string>> = { VERIFIER: 'cyan', OPERATOR: 'blue' }

export default function RegistrationsPage({ onHandled }: { onHandled?: () => void }) {
  const { message } = AntApp.useApp()
  const [rows, setRows] = useState<PendingUser[]>([])
  const [loading, setLoading] = useState(true)
  const [rejecting, setRejecting] = useState<PendingUser | null>(null)
  const [reason, setReason] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await api.get<PendingUser[]>('/api/admin/registrations'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const review = async (id: number, approve: boolean, why?: string) => {
    try {
      await api.post(`/api/admin/registrations/${id}/review`, { approve, reason: why })
      message.success(approve ? '已通过申请' : '已驳回申请')
      void load()
      onHandled?.()
    } catch (e) {
      message.error((e as ApiError).message)
    }
  }

  return (
    <>
      <PageHeader
        title="注册审核"
        description={
          rows.length
            ? `${rows.length} 份申请待处理`
            : '核销人员与运营人员的账号申请将在此处等待审批'
        }
      />

      <Card>
        <Table
          rowKey="id"
          loading={loading}
          dataSource={rows}
          pagination={false}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无待审申请" />,
          }}
          columns={[
            {
              title: '申请人',
              width: 180,
              render: (_, r) => (
                <div>
                  <Typography.Text strong>{r.display_name}</Typography.Text>
                  <div>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {r.username}
                      {r.phone ? ` · ${r.phone}` : ''}
                    </Typography.Text>
                  </div>
                </div>
              ),
            },
            {
              title: '申请角色',
              dataIndex: 'role',
              width: 110,
              render: (v: Role) => <Tag color={ROLE_COLOR[v]}>{ROLE_LABEL[v]}</Tag>,
            },
            {
              title: '所属门店',
              width: 240,
              render: (_, r) =>
                r.store_name ? (
                  <span>
                    <Tag>{r.store_district}</Tag>
                    {r.store_name}
                  </span>
                ) : (
                  <Typography.Text type="secondary">—</Typography.Text>
                ),
            },
            {
              title: '提交时间',
              dataIndex: 'created_at',
              width: 170,
              render: (v: string) => (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {dayjs(v).format('YYYY-MM-DD HH:mm')}
                </Typography.Text>
              ),
            },
            {
              title: '操作',
              width: 140,
              render: (_, r) => (
                <Space>
                  <Typography.Link onClick={() => review(r.id, true)}>通过</Typography.Link>
                  <Typography.Link
                    type="danger"
                    onClick={() => {
                      setRejecting(r)
                      setReason('')
                    }}
                  >
                    驳回
                  </Typography.Link>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        open={!!rejecting}
        title={`驳回 ${rejecting?.display_name ?? ''} 的申请`}
        onCancel={() => setRejecting(null)}
        onOk={async () => {
          if (!rejecting) return
          await review(rejecting.id, false, reason.trim() || undefined)
          setRejecting(null)
        }}
        okText="确认驳回"
        okButtonProps={{ danger: true }}
      >
        <Typography.Paragraph type="secondary">
          驳回原因会展示给申请人，便于其补齐资料后重新提交。
        </Typography.Paragraph>
        <Input.TextArea
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="例如：门店选择有误，请选择实际任职门店"
          maxLength={256}
          showCount
        />
      </Modal>
    </>
  )
}
