import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Row,
  Segmented,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../api/client'
import { ERROR_MESSAGE } from '../api/types'
import type {
  AlertSettings,
  ConfigChange,
  OperatorSettings,
  Paged,
  RiskFactorWeights,
  RiskPolicyLevel,
} from '../api/types'
import { PageHeader } from '../components/PageHeader'

const RISK_PRESETS: Record<Exclude<RiskPolicyLevel, 'CUSTOM'>, {
  title: string
  description: string
  hard: number
  review: number
  block: number
}> = {
  LOW: { title: '低保护', description: '适合普通低价值活动，减少用户打扰', hard: 15, review: 50, block: 80 },
  MEDIUM: { title: '中保护', description: '兼顾转化与风险，推荐作为全局默认', hard: 10, review: 40, block: 70 },
  HIGH: { title: '高保护', description: '适合热门或高价值活动，更早进入人工审核', hard: 7, review: 30, block: 60 },
}

const FACTORS: Array<{ key: keyof RiskFactorWeights; label: string; description: string }> = [
  { key: 'frequency', label: '短时领取频率', description: '窗口内请求越密集，风险贡献越高' },
  { key: 'new_account', label: '新注册账号', description: '注册时间较短的账号增加风险分' },
  { key: 'low_redeem', label: '历史核销率偏低', description: '长期领而不用可能存在囤券行为' },
  { key: 'unused_coupons', label: '未使用券较多', description: '当前持有大量未使用券' },
  { key: 'risk_history', label: '历史风险记录', description: '曾命中风险规则的账号' },
  { key: 'high_value', label: '高价值活动', description: '优惠价值较高时增强保护' },
]

const ALERTS: Array<{
  key: keyof AlertSettings
  label: string
  description: string
  suffix: string
  percent?: boolean
}> = [
  { key: 'quota_usage', label: '每日额度接近耗尽', description: '当日额度使用率达到阈值', suffix: '%', percent: true },
  { key: 'exhaustion_hours', label: '预计即将耗尽', description: '预计库存或额度将在指定时间内耗尽', suffix: '小时' },
  { key: 'claim_growth', label: '领取量突增', description: '较上一时段增长达到阈值', suffix: '%', percent: true },
  { key: 'risk_rate', label: '风险率升高', description: '风险请求占比达到阈值', suffix: '%', percent: true },
  { key: 'pending_risks', label: '待处理风险积压', description: '人工审核待办达到阈值', suffix: '条' },
  { key: 'redeem_rate_gap', label: '核销率显著偏低', description: '低于活动平均核销率的差值', suffix: '个百分点', percent: true },
]

const OBJECT_LABEL: Record<ConfigChange['object_type'], string> = {
  OPERATOR_SETTINGS: '人群定义',
  RISK_POLICY: '风控策略',
  ALERT_SETTINGS: '异常提醒',
  CAMPAIGN: '活动配置',
}

const formatTime = (value: string) =>
  new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value))

export default function SettingsPage() {
  const { message } = AntApp.useApp()
  const [settings, setSettings] = useState<OperatorSettings | null>(null)
  const [changes, setChanges] = useState<Paged<ConfigChange> | null>(null)
  const [loading, setLoading] = useState(true)
  const [changesLoading, setChangesLoading] = useState(false)
  const [saving, setSaving] = useState<'audience' | 'risk' | 'alerts' | null>(null)
  const [riskLevel, setRiskLevel] = useState<RiskPolicyLevel>('MEDIUM')
  const [audienceForm] = Form.useForm()
  const [riskForm] = Form.useForm()
  const [alertForm] = Form.useForm()

  const applySettings = useCallback((value: OperatorSettings) => {
    setSettings(value)
    setRiskLevel(value.default_risk_policy.level)
    audienceForm.setFieldsValue(value.audience_thresholds)
    riskForm.setFieldsValue({
      name: value.default_risk_policy.name,
      window_seconds: value.default_risk_policy.hard_rules.window_seconds,
      hard_threshold: value.default_risk_policy.hard_rules.hard_threshold,
      review_threshold: value.default_risk_policy.review_threshold,
      block_threshold: value.default_risk_policy.block_threshold,
      ...value.default_risk_policy.factor_weights,
    })
    const alertValues = Object.fromEntries(
      ALERTS.map(({ key, percent }) => [
        key,
        {
          ...value.alert_settings[key],
          threshold: percent
            ? value.alert_settings[key].threshold * 100
            : value.alert_settings[key].threshold,
        },
      ]),
    )
    alertForm.setFieldsValue(alertValues)
  }, [alertForm, audienceForm, riskForm])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      applySettings(await api.get<OperatorSettings>('/api/operator/settings'))
    } catch (error) {
      const err = error as ApiError
      message.error(ERROR_MESSAGE[err.code] ?? err.message)
    } finally {
      setLoading(false)
    }
  }, [applySettings, message])

  const loadChanges = useCallback(async (page = 1) => {
    setChangesLoading(true)
    try {
      setChanges(
        await api.get<Paged<ConfigChange>>(
          `/api/operator/settings/changes?page=${page}&page_size=10`,
        ),
      )
    } catch (error) {
      const err = error as ApiError
      message.error(ERROR_MESSAGE[err.code] ?? err.message)
    } finally {
      setChangesLoading(false)
    }
  }, [message])

  useEffect(() => {
    void load()
    void loadChanges()
  }, [load, loadChanges])

  const handleError = async (error: unknown) => {
    const err = error as ApiError
    message.error(ERROR_MESSAGE[err.code] ?? err.message)
    if (err.code === 'CONFIG_VERSION_CONFLICT') await load()
  }

  const saveAudience = async () => {
    if (!settings) return
    const values = await audienceForm.validateFields()
    if (values.active_days >= values.dormant_days) {
      message.warning('活跃用户天数必须小于沉睡用户天数')
      return
    }
    if (values.low_redeem_rate >= values.high_redeem_rate) {
      message.warning('低核销率阈值必须小于高核销率阈值')
      return
    }
    setSaving('audience')
    try {
      applySettings(
        await api.patch<OperatorSettings>('/api/operator/settings/audiences', {
          expected_version: settings.version,
          thresholds: values,
        }),
      )
      message.success('人群定义已更新，继承全局配置的活动将使用新口径')
      void loadChanges()
    } catch (error) {
      await handleError(error)
    } finally {
      setSaving(null)
    }
  }

  const saveRisk = async () => {
    if (!settings) return
    setSaving('risk')
    try {
      let custom: Record<string, unknown> | undefined
      if (riskLevel === 'CUSTOM') {
        const values = await riskForm.validateFields()
        if (values.review_threshold >= values.block_threshold) {
          message.warning('人工审核线必须小于自动拦截线')
          return
        }
        custom = {
          name: values.name,
          hard_rules: {
            window_seconds: values.window_seconds,
            hard_threshold: values.hard_threshold,
          },
          factor_weights: Object.fromEntries(FACTORS.map(({ key }) => [key, values[key]])),
          review_threshold: values.review_threshold,
          block_threshold: values.block_threshold,
        }
      }
      applySettings(
        await api.patch<OperatorSettings>('/api/operator/settings/risk', {
          expected_version: settings.version,
          level: riskLevel,
          ...(custom ? { custom } : {}),
        }),
      )
      message.success('全局风控策略已更新')
      void loadChanges()
    } catch (error) {
      await handleError(error)
    } finally {
      setSaving(null)
    }
  }

  const saveAlerts = async () => {
    if (!settings) return
    const values = await alertForm.validateFields()
    const next = Object.fromEntries(
      ALERTS.map(({ key, percent }) => [
        key,
        {
          enabled: values[key].enabled,
          threshold: percent ? values[key].threshold / 100 : values[key].threshold,
        },
      ]),
    )
    setSaving('alerts')
    try {
      applySettings(
        await api.patch<OperatorSettings>('/api/operator/settings/alerts', {
          expected_version: settings.version,
          settings: next,
        }),
      )
      message.success('异常提醒设置已更新')
      void loadChanges()
    } catch (error) {
      await handleError(error)
    } finally {
      setSaving(null)
    }
  }

  const currentPreset = riskLevel === 'CUSTOM' ? null : RISK_PRESETS[riskLevel]

  return (
    <>
      <PageHeader
        title="运营设置"
        description="统一管理目标人群、默认风控策略和驾驶舱提醒；活动级覆盖不受全局更新影响"
        extra={
          settings ? (
            <Space direction="vertical" size={0} align="end">
              <Tag color="blue">配置版本 v{settings.version}</Tag>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {settings.updated_by ? `${settings.updated_by} · ` : ''}{formatTime(settings.updated_at)}
              </Typography.Text>
            </Space>
          ) : null
        }
      />

      <Card loading={loading}>
        {!loading && !settings ? (
          <Empty description="运营设置暂不可用" />
        ) : (
          <Tabs
            items={[
              {
                key: 'audience',
                label: '人群定义',
                children: (
                  <div style={{ maxWidth: 880 }}>
                    <Alert
                      type="info"
                      showIcon
                      message="人群口径全局统一"
                      description="活动可同时选择多个人群并按并集投放。修改后，继承全局配置的运行中活动会立即使用新口径。"
                      style={{ marginBottom: 20 }}
                    />
                    <Form form={audienceForm} layout="vertical" requiredMark={false}>
                      <Row gutter={20}>
                        <Col xs={24} md={12}>
                          <Card size="small" title="新用户与活跃用户" style={{ height: '100%' }}>
                            <Form.Item name="new_user_days" label="新用户注册天数" rules={[{ required: true }]}>
                              <InputNumber min={1} max={365} addonAfter="天内" style={{ width: '100%' }} />
                            </Form.Item>
                            <Form.Item name="active_days" label="活跃用户行为窗口" rules={[{ required: true }]}>
                              <InputNumber min={1} max={365} addonAfter="天内" style={{ width: '100%' }} />
                            </Form.Item>
                            <Form.Item name="dormant_days" label="沉睡用户无行为时长" rules={[{ required: true }]}>
                              <InputNumber min={1} max={3650} addonAfter="天以上" style={{ width: '100%' }} />
                            </Form.Item>
                          </Card>
                        </Col>
                        <Col xs={24} md={12}>
                          <Card size="small" title="高低核销用户" style={{ height: '100%' }}>
                            <Form.Item name="redeem_sample_size" label="最少历史领取样本" rules={[{ required: true }]}>
                              <InputNumber min={1} max={1000} addonAfter="张" style={{ width: '100%' }} />
                            </Form.Item>
                            <Form.Item name="high_redeem_rate" label="高核销用户阈值" rules={[{ required: true }]}>
                              <InputNumber min={0} max={100} addonAfter="% 及以上" style={{ width: '100%' }} />
                            </Form.Item>
                            <Form.Item name="low_redeem_rate" label="低核销用户阈值" rules={[{ required: true }]}>
                              <InputNumber min={0} max={100} addonAfter="% 及以下" style={{ width: '100%' }} />
                            </Form.Item>
                          </Card>
                        </Col>
                      </Row>
                      <Button type="primary" loading={saving === 'audience'} onClick={saveAudience} style={{ marginTop: 20 }}>
                        保存人群定义
                      </Button>
                    </Form>
                  </div>
                ),
              },
              {
                key: 'risk',
                label: '风控策略',
                children: (
                  <div style={{ maxWidth: 960 }}>
                    <Alert
                      type="success"
                      showIcon
                      message="规则负责裁决，AI 只负责解释"
                      description="相同特征与策略始终产生相同分数和结论。活动可继承此默认策略，也可单独覆盖。"
                      style={{ marginBottom: 20 }}
                    />
                    <Typography.Title level={5}>保护等级</Typography.Title>
                    <Segmented
                      block
                      value={riskLevel}
                      onChange={(value) => setRiskLevel(value as RiskPolicyLevel)}
                      options={[
                        { value: 'LOW', label: '低保护' },
                        { value: 'MEDIUM', label: '中保护' },
                        { value: 'HIGH', label: '高保护' },
                        { value: 'CUSTOM', label: '自定义' },
                      ]}
                    />

                    {currentPreset ? (
                      <Card size="small" style={{ marginTop: 20 }}>
                        <Descriptions column={{ xs: 1, sm: 2, md: 4 }} size="small">
                          <Descriptions.Item label="策略说明" span={2}>{currentPreset.description}</Descriptions.Item>
                          <Descriptions.Item label="频率硬阈值">{currentPreset.hard} 次</Descriptions.Item>
                          <Descriptions.Item label="分数区间">
                            <Tag color="green">&lt; {currentPreset.review} 放行</Tag>
                            <Tag color="orange">{currentPreset.review}–{currentPreset.block - 1} 审核</Tag>
                            <Tag color="red">≥ {currentPreset.block} 拦截</Tag>
                          </Descriptions.Item>
                        </Descriptions>
                      </Card>
                    ) : (
                      <Form form={riskForm} layout="vertical" requiredMark={false} style={{ marginTop: 20 }}>
                        <Row gutter={20}>
                          <Col xs={24} md={12}>
                            <Card size="small" title="裁决阈值">
                              <Form.Item name="name" label="策略名称" rules={[{ required: true }]}>
                                <Input maxLength={64} placeholder="例如：大促高价值保护" />
                              </Form.Item>
                              <Form.Item name="window_seconds" label="频率统计窗口" rules={[{ required: true }]}>
                                <InputNumber min={1} max={3600} addonAfter="秒" style={{ width: '100%' }} />
                              </Form.Item>
                              <Form.Item name="hard_threshold" label="频率硬拦截阈值" rules={[{ required: true }]}>
                                <InputNumber min={1} max={10000} addonAfter="次" style={{ width: '100%' }} />
                              </Form.Item>
                              <Space.Compact block>
                                <Form.Item name="review_threshold" label="人工审核线" rules={[{ required: true }]} style={{ width: '50%' }}>
                                  <InputNumber min={0} max={99} style={{ width: '100%' }} />
                                </Form.Item>
                                <Form.Item name="block_threshold" label="自动拦截线" rules={[{ required: true }]} style={{ width: '50%' }}>
                                  <InputNumber min={1} max={100} style={{ width: '100%' }} />
                                </Form.Item>
                              </Space.Compact>
                            </Card>
                          </Col>
                          <Col xs={24} md={12}>
                            <Card size="small" title="因素最高贡献分">
                              {FACTORS.map((factor) => (
                                <Form.Item
                                  key={factor.key}
                                  name={factor.key}
                                  label={factor.label}
                                  tooltip={factor.description}
                                  rules={[{ required: true }]}
                                >
                                  <InputNumber min={0} max={100} addonAfter="分" style={{ width: '100%' }} />
                                </Form.Item>
                              ))}
                            </Card>
                          </Col>
                        </Row>
                      </Form>
                    )}
                    <Button type="primary" loading={saving === 'risk'} onClick={saveRisk} style={{ marginTop: 20 }}>
                      保存默认风控策略
                    </Button>
                  </div>
                ),
              },
              {
                key: 'alerts',
                label: '异常提醒',
                children: (
                  <div style={{ maxWidth: 880 }}>
                    <Alert
                      type="info"
                      showIcon
                      message="提醒仅在运营驾驶舱展示"
                      description="关闭某项后不再产生该类提醒。阈值修改不会影响活动投放和风险裁决。"
                      style={{ marginBottom: 20 }}
                    />
                    <Form form={alertForm} layout="vertical" requiredMark={false}>
                      <Row gutter={[16, 16]}>
                        {ALERTS.map((alert) => (
                          <Col xs={24} md={12} key={alert.key}>
                            <Card size="small" style={{ height: '100%' }}>
                              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                                <div style={{ flex: 1 }}>
                                  <Typography.Text strong>{alert.label}</Typography.Text>
                                  <div>
                                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                      {alert.description}
                                    </Typography.Text>
                                  </div>
                                </div>
                                <Form.Item name={[alert.key, 'enabled']} valuePropName="checked" noStyle>
                                  <Switch checkedChildren="启用" unCheckedChildren="关闭" />
                                </Form.Item>
                              </div>
                              <Form.Item name={[alert.key, 'threshold']} label="触发阈值" rules={[{ required: true }]} style={{ marginTop: 16, marginBottom: 0 }}>
                                <InputNumber min={0} precision={alert.percent ? 1 : 0} addonAfter={alert.suffix} style={{ width: '100%' }} />
                              </Form.Item>
                            </Card>
                          </Col>
                        ))}
                      </Row>
                      <Button type="primary" loading={saving === 'alerts'} onClick={saveAlerts} style={{ marginTop: 20 }}>
                        保存提醒设置
                      </Button>
                    </Form>
                  </div>
                ),
              },
              {
                key: 'changes',
                label: '变更记录',
                children: (
                  <Table
                    rowKey="id"
                    loading={changesLoading}
                    dataSource={changes?.items ?? []}
                    locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无配置变更" /> }}
                    pagination={{
                      current: changes?.page ?? 1,
                      pageSize: changes?.page_size ?? 10,
                      total: changes?.total ?? 0,
                      showSizeChanger: false,
                      onChange: (page) => void loadChanges(page),
                    }}
                    expandable={{
                      expandedRowRender: (record) => (
                        <Row gutter={16}>
                          <Col xs={24} md={12}>
                            <Typography.Text type="secondary">修改前</Typography.Text>
                            <pre style={{ margin: '8px 0 0', padding: 12, background: '#f6f8fb', borderRadius: 6, overflow: 'auto', fontSize: 12 }}>
                              {JSON.stringify(record.before_data, null, 2)}
                            </pre>
                          </Col>
                          <Col xs={24} md={12}>
                            <Typography.Text type="secondary">修改后</Typography.Text>
                            <pre style={{ margin: '8px 0 0', padding: 12, background: '#f6f8fb', borderRadius: 6, overflow: 'auto', fontSize: 12 }}>
                              {JSON.stringify(record.after_data, null, 2)}
                            </pre>
                          </Col>
                        </Row>
                      ),
                    }}
                    columns={[
                      {
                        title: '配置范围',
                        dataIndex: 'object_type',
                        width: 140,
                        render: (value: ConfigChange['object_type']) => <Tag color="blue">{OBJECT_LABEL[value]}</Tag>,
                      },
                      { title: '操作', dataIndex: 'action', width: 100, render: () => '更新' },
                      { title: '修改人', dataIndex: 'changed_by', width: 120 },
                      {
                        title: '修改时间',
                        dataIndex: 'created_at',
                        width: 190,
                        render: (value: string) => formatTime(value),
                      },
                      {
                        title: '版本变化',
                        render: (_, record) => {
                          const before = record.before_data.version
                          const after = record.after_data.version
                          return before !== undefined && after !== undefined ? `v${String(before)} → v${String(after)}` : '—'
                        },
                      },
                    ]}
                  />
                ),
              },
            ]}
          />
        )}
      </Card>
    </>
  )
}
