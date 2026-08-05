import { useEffect, useState, useCallback } from 'react'
import { Table, Tag, Button, Space, Card, Empty, Modal, Form, Input, InputNumber, Select, Switch, message } from 'antd'
import { PlusOutlined, ReloadOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useI18n } from '../i18n'

interface RiskRule {
  id: string; tool_name: string; match_json: any; tier: string
  autonomous: boolean; enabled: boolean; priority: number
  updated_at: number; updated_by: string
}

const TIER_COLORS: Record<string, string> = {
  low: 'green', medium: 'blue', recover: 'orange',
  reversible: 'gold', irreversible: 'red',
}
const TIER_KEYS: Record<string, string> = {
  low: 'rules.low', medium: 'rules.medium', recover: 'rules.recover',
  reversible: 'rules.reversible', irreversible: 'rules.irreversible',
}

function RiskRules() {
  const { t } = useI18n()
  const [rules, setRules] = useState<RiskRule[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<RiskRule | null>(null)
  const [form] = Form.useForm()

  const fetchRules = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/risk_rules')
      const data = await res.json()
      setRules(data)
    } catch (e) {
      console.error('fetchRules failed:', e)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchRules()
  }, [fetchRules])

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      const rule = {
        ...values,
        id: editing?.id,
        match_json: values.match_json ? JSON.parse(values.match_json) : null,
        updated_by: 'web-user',
      }
      const url = editing ? `/api/risk_rules/${editing.id}` : '/api/risk_rules'
      const method = editing ? 'PUT' : 'POST'
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(rule),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      message.success(editing ? t('rules.ruleUpdated') : t('rules.ruleCreated'))
      setModalOpen(false)
      form.resetFields()
      fetchRules()
    } catch (e) {
      message.error(t('rules.saveFailed') + ': ' + (e as Error).message)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      const res = await fetch(`/api/risk_rules/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      message.success(t('rules.ruleDeleted'))
      fetchRules()
    } catch (e) {
      message.error(t('rules.deleteFailed'))
    }
  }

  const columns = [
    { title: t('rules.tool'), dataIndex: 'tool_name', key: 'tool', width: 160 },
    {
      title: t('rules.match'), key: 'match', width: 200,
      render: (_: any, r: RiskRule) => r.match_json ? JSON.stringify(r.match_json) : t('rules.matchAny'),
    },
    {
      title: t('rules.tier'), dataIndex: 'tier', key: 'tier', width: 100,
      render: (v: string) => <Tag color={TIER_COLORS[v] || 'default'}>{t(TIER_KEYS[v] as any) || v}</Tag>,
    },
    {
      title: t('rules.autoExec'), dataIndex: 'autonomous', key: 'auto', width: 90,
      render: (v: boolean, r: RiskRule) => (
        <Switch checked={v} disabled={r.tier === 'irreversible'} size="small" />
      ),
    },
    {
      title: t('rules.enabled'), dataIndex: 'enabled', key: 'enabled', width: 70,
      render: (v: boolean) => <Tag color={v ? 'success' : 'default'}>{v ? 'ON' : 'OFF'}</Tag>,
    },
    { title: t('rules.priority'), dataIndex: 'priority', key: 'pri', width: 70 },
    {
      title: t('rules.action'), key: 'action', width: 140,
      render: (_: any, r: RiskRule) => (
        <Space>
          <Button size="small" icon={<EditOutlined />}
            onClick={() => { setEditing(r); form.setFieldsValue({ ...r, match_json: r.match_json ? JSON.stringify(r.match_json) : '' }); setModalOpen(true) }}>
            {t('rules.edit')}
          </Button>
          <Button size="small" danger icon={<DeleteOutlined />}
            onClick={() => handleDelete(r.id)} />
        </Space>
      ),
    },
  ]

  return (
    <div style={{ height: '100%', overflow: 'auto' }}>
      <Card
        size="small"
        title={`${t('rules.title')} (${rules.length} ${t('rules.count')})`}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchRules} size="small">{t('rules.refresh')}</Button>
            <Button type="primary" icon={<PlusOutlined />} size="small"
              onClick={() => { setEditing(null); form.resetFields(); setModalOpen(true) }}>
              {t('rules.add')}
            </Button>
          </Space>
        }
      >
        {rules.length === 0 && !loading ? (
          <Empty description={t('rules.empty')} />
        ) : (
          <Table
            dataSource={rules}
            columns={columns}
            rowKey="id"
            loading={loading}
            size="small"
            pagination={{ pageSize: 20, size: 'small' }}
          />
        )}
      </Card>

      <Modal
        title={editing ? t('rules.editRule') : t('rules.addRule')}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => { setModalOpen(false); form.resetFields() }}
        width={520}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="tool_name" label={t('rules.toolName')} rules={[{ required: true }]}>
            <Input placeholder={t('rules.toolPlaceholder')} />
          </Form.Item>
          <Form.Item name="match_json" label={t('rules.matchOptional')}>
            <Input.TextArea placeholder={t('rules.matchPlaceholder')} rows={2} />
          </Form.Item>
          <Form.Item name="tier" label={t('rules.tier')} rules={[{ required: true }]}>
            <Select options={Object.entries(TIER_KEYS).map(([k, v]) => ({ value: k, label: t(v as any) }))} />
          </Form.Item>
          <Form.Item name="autonomous" label={t('rules.allowAuto')} valuePropName="checked">
            <Switch disabled={Form.useWatch('tier', form) === 'irreversible'} />
          </Form.Item>
          <Form.Item name="enabled" label={t('rules.enabled')} valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
          <Form.Item name="priority" label={t('rules.priorityLabel')} initialValue={0}>
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default RiskRules
