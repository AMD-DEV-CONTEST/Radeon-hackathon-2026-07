import { useEffect, useState, useCallback } from 'react'
import { Table, Tag, Button, Space, Card, Empty, message } from 'antd'
import { CheckOutlined, CloseOutlined, ReloadOutlined } from '@ant-design/icons'
import { useI18n } from '../i18n'

interface Approval {
  id: string; session_id: string; tool_name: string; args: any
  risk_level: string; dry_run: any; status: string; decided_by: string; ts: number
}

const RISK_COLORS: Record<string, string> = {
  high: 'red', medium: 'orange', low: 'green', destructive: 'volcano',
}
const RISK_KEYS: Record<string, string> = {
  high: 'approval.high', medium: 'approval.medium', low: 'approval.low', destructive: 'approval.destructive',
}
const STATUS_KEYS: Record<string, string> = {
  pending: 'approval.pending', approved: 'approval.approved', rejected: 'approval.rejected',
}

function ApprovalCenter() {
  const { t } = useI18n()
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [loading, setLoading] = useState(false)

  const fetchApprovals = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/approvals')
      const data = await res.json()
      setApprovals(data)
    } catch (e) {
      console.error('fetchApprovals failed:', e)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchApprovals()
    const t = setInterval(fetchApprovals, 5000)
    return () => clearInterval(t)
  }, [fetchApprovals])

  const decide = async (id: string, status: string) => {
    try {
      const res = await fetch(`/api/approvals/${id}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, decided_by: 'web-user' }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      message.success(`${status === 'approved' ? t('approval.approved') : t('approval.rejected')}: ${id}`)
    } catch (e) {
      console.error('decide failed:', e)
      message.error(t('approval.opFailed'))
    }
    fetchApprovals()
  }

  const columns = [
    {
      title: t('approval.risk'), dataIndex: 'risk_level', key: 'risk', width: 80,
      render: (v: string) => <Tag color={RISK_COLORS[v] || 'default'}>{t(RISK_KEYS[v] as any) || v}</Tag>,
    },
    { title: t('approval.tool'), dataIndex: 'tool_name', key: 'tool', width: 140 },
    {
      title: t('approval.args'), key: 'args',
      render: (_: any, r: Approval) => (
        <span style={{ fontSize: 12, fontFamily: 'monospace' }}>{JSON.stringify(r.args)}</span>
      ),
    },
    {
      title: t('approval.preview'), key: 'dry_run', width: 220,
      render: (_: any, r: Approval) => r.dry_run?.message || '-',
    },
    {
      title: t('approval.status'), dataIndex: 'status', key: 'status', width: 90,
      render: (v: string) => (
        <Tag color={v === 'approved' ? 'success' : v === 'rejected' ? 'error' : 'processing'}>
          {t(STATUS_KEYS[v] as any) || v}
        </Tag>
      ),
    },
    {
      title: t('approval.approver'), dataIndex: 'decided_by', key: 'by', width: 120,
      render: (v: string) => v || '-',
    },
    {
      title: t('approval.action'), key: 'action', width: 160,
      render: (_: any, r: Approval) =>
        r.status === 'pending' ? (
          <Space>
            <Button type="primary" size="small" icon={<CheckOutlined />}
              onClick={() => decide(r.id, 'approved')}>{t('approval.approve')}</Button>
            <Button danger size="small" icon={<CloseOutlined />}
              onClick={() => decide(r.id, 'rejected')}>{t('approval.reject')}</Button>
          </Space>
        ) : null,
    },
  ]

  const pending = approvals.filter(a => a.status === 'pending')

  return (
    <div style={{ height: '100%', overflow: 'auto' }}>
      <Card
        size="small"
        title={`${t('approval.title')} (${pending.length} ${t('approval.pendingCount')} / ${approvals.length} ${t('approval.total')})`}
        extra={<Button icon={<ReloadOutlined />} onClick={fetchApprovals} size="small">{t('approval.refresh')}</Button>}
      >
        {approvals.length === 0 && !loading ? (
          <Empty description={t('approval.empty')} />
        ) : (
          <Table
            dataSource={approvals}
            columns={columns}
            rowKey="id"
            loading={loading}
            size="small"
            pagination={{ pageSize: 20, size: 'small' }}
          />
        )}
      </Card>
    </div>
  )
}

export default ApprovalCenter
