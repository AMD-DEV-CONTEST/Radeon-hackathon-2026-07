import { useEffect, useState, useCallback } from 'react'
import {
  Table, Tag, Button, Space, Card, Empty, Modal, Form, Input, Select,
  Statistic, Row, Col, message, Tooltip, Typography,
} from 'antd'
import {
  PlusOutlined, ReloadOutlined, EditOutlined, DeleteOutlined,
  BookOutlined, CheckOutlined, CloseOutlined, SearchOutlined,
} from '@ant-design/icons'
import { useI18n } from '../i18n'

const { TextArea } = Input
const { Text } = Typography

interface Runbook {
  id: string
  title: string
  content: string
  tags: string
  source: 'manual' | 'agent_generated'
  status: 'approved' | 'pending_review' | 'rejected'
  session_id?: string
  confidence?: number
  created_at: number
  updated_at: number
  updated_by: string
}

interface Stats {
  total: number
  approved: number
  pending_review: number
  rejected: number
  manual: number
  agent_generated: number
}

const STATUS_COLORS: Record<string, string> = {
  approved: 'success',
  pending_review: 'warning',
  rejected: 'error',
}
const STATUS_KEYS: Record<string, string> = {
  approved: 'kb.approved',
  pending_review: 'kb.pendingReview',
  rejected: 'kb.rejected',
}
const SOURCE_COLORS: Record<string, string> = {
  manual: 'blue',
  agent_generated: 'purple',
}
const SOURCE_KEYS: Record<string, string> = {
  manual: 'kb.manual',
  agent_generated: 'kb.agentGen',
}

function KnowledgeBase() {
  const { t, lang } = useI18n()
  const [runbooks, setRunbooks] = useState<Runbook[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Runbook | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [searching, setSearching] = useState(false)
  const [filterStatus, setFilterStatus] = useState('')
  const [form] = Form.useForm()

  const fetchRunbooks = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (filterStatus) params.set('status', filterStatus)
      const res = await fetch(`/api/runbooks?${params}`)
      const data = await res.json()
      setRunbooks(Array.isArray(data) ? data : [])
    } catch (e) {
      console.error('fetchRunbooks failed:', e)
      message.error(t('kb.loadFailed'))
    }
    setLoading(false)
  }, [filterStatus])

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch('/api/runbooks/stats')
      const data = await res.json()
      setStats(data)
    } catch (e) {
      console.error('fetchStats failed:', e)
    }
  }, [])

  useEffect(() => {
    fetchRunbooks()
    fetchStats()
  }, [fetchRunbooks, fetchStats])

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      const rb = {
        ...values,
        id: editing?.id,
        updated_by: 'web-user',
      }
      const url = editing ? `/api/runbooks/${editing.id}` : '/api/runbooks'
      const method = editing ? 'PUT' : 'POST'
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(rb),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      message.success(editing ? t('kb.updated') : t('kb.created'))
      setModalOpen(false)
      form.resetFields()
      fetchRunbooks()
      fetchStats()
    } catch (e) {
      message.error(t('kb.saveFailed') + ': ' + (e as Error).message)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      const res = await fetch(`/api/runbooks/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      message.success(t('kb.deleted'))
      fetchRunbooks()
      fetchStats()
    } catch (e) {
      message.error(t('kb.deleteFailed'))
    }
  }

  const handleReview = async (id: string, status: 'approved' | 'rejected') => {
    try {
      const res = await fetch(`/api/runbooks/${id}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, decided_by: 'web-user' }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      message.success(status === 'approved' ? t('kb.reviewPassed') : t('kb.reviewRejected'))
      fetchRunbooks()
      fetchStats()
    } catch (e) {
      message.error(t('kb.reviewFailed'))
    }
  }

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      setSearchResults([])
      return
    }
    setSearching(true)
    try {
      const res = await fetch(`/api/runbooks/search?q=${encodeURIComponent(searchQuery)}&limit=5`)
      const data = await res.json()
      setSearchResults(data.results || [])
    } catch (e) {
      message.error(t('kb.searchFailed'))
    }
    setSearching(false)
  }

  const columns = [
    {
      title: t('kb.title'), dataIndex: 'title', key: 'title',
      render: (v: string, r: Runbook) => (
        <Tooltip title={r.content.slice(0, 100) + '...'} placement="topLeft">
          <Text strong>{v}</Text>
        </Tooltip>
      ),
    },
    { title: t('kb.tags'), dataIndex: 'tags', key: 'tags', width: 180,
      render: (v: string) => v ? v.split(',').map((t: string) =>
        <Tag key={t} color="blue" style={{ marginBottom: 2 }}>{t.trim()}</Tag>
      ) : '—',
    },
    {
      title: t('kb.source'), dataIndex: 'source', key: 'source', width: 100,
      render: (v: string) => <Tag color={SOURCE_COLORS[v]}>{t(SOURCE_KEYS[v] as any) || v}</Tag>,
    },
    {
      title: t('kb.status'), dataIndex: 'status', key: 'status', width: 90,
      render: (v: string) => <Tag color={STATUS_COLORS[v]}>{t(STATUS_KEYS[v] as any) || v}</Tag>,
    },
    {
      title: t('kb.confidence'), dataIndex: 'confidence', key: 'conf', width: 80,
      render: (v: number) => v != null ? `${(v * 100).toFixed(0)}%` : '—',
    },
    {
      title: t('kb.updatedAt'), dataIndex: 'updated_at', key: 'ts', width: 130,
      render: (v: number) => v ? new Date(v * 1000).toLocaleString(lang === 'zh' ? 'zh-CN' : 'en-US',
        { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—',
    },
    {
      title: t('kb.action'), key: 'action', width: 180,
      render: (_: any, r: Runbook) => (
        <Space size="small">
          {r.status === 'pending_review' && (
            <>
              <Button size="small" type="primary" icon={<CheckOutlined />}
                onClick={() => handleReview(r.id, 'approved')}>
                {t('kb.pass')}
              </Button>
              <Button size="small" danger icon={<CloseOutlined />}
                onClick={() => handleReview(r.id, 'rejected')}>
                {t('kb.reject')}
              </Button>
            </>
          )}
          <Button size="small" icon={<EditOutlined />}
            onClick={() => {
              setEditing(r)
              form.setFieldsValue(r)
              setModalOpen(true)
            }} />
          <Button size="small" danger icon={<DeleteOutlined />}
            onClick={() => handleDelete(r.id)} />
        </Space>
      ),
    },
  ]

  return (
    <div style={{ height: '100%', overflow: 'auto', paddingRight: 4 }}>
      {/* 统计卡片 */}
      {stats && (
        <Card size="small" style={{ marginBottom: 12 }}>
          <Row gutter={16}>
            <Col span={4}>
              <Statistic title={t('kb.total')} value={stats.total} prefix={<BookOutlined />} />
            </Col>
            <Col span={4}>
              <Statistic title={t('kb.approved')} value={stats.approved} valueStyle={{ color: '#52c41a' }} />
            </Col>
            <Col span={4}>
              <Statistic title={t('kb.pendingReview')} value={stats.pending_review}
                valueStyle={{ color: stats.pending_review > 0 ? '#faad14' : undefined }} />
            </Col>
            <Col span={4}>
              <Statistic title={t('kb.rejected')} value={stats.rejected} valueStyle={{ color: '#ff4d4f' }} />
            </Col>
            <Col span={4}>
              <Statistic title={t('kb.manualAdd')} value={stats.manual} />
            </Col>
            <Col span={4}>
              <Statistic title={t('kb.agentGen')} value={stats.agent_generated}
                valueStyle={{ color: stats.agent_generated > 0 ? '#722ed1' : undefined }} />
            </Col>
          </Row>
        </Card>
      )}

      {/* 检索测试 */}
      <Card size="small" style={{ marginBottom: 12 }} title={t('kb.searchTest')}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder={t('kb.searchPlaceholder')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onPressEnter={handleSearch}
            prefix={<SearchOutlined />}
          />
          <Button type="primary" onClick={handleSearch} loading={searching}>
            {t('kb.search')}
          </Button>
        </Space.Compact>
        {searchResults.length > 0 && (
          <div style={{ marginTop: 8 }}>
            {searchResults.map((r: any, i: number) => (
              <Card key={i} size="small" style={{ marginBottom: 6,
                background: 'rgba(255,255,255,0.02)' }}>
                <Space>
                  <Tag color={r.match_type === 'vector' ? 'green' : 'blue'}>
                    {r.match_type === 'vector' ? t('kb.vector') : t('kb.bm25')}
                  </Tag>
                  <Tag>score: {r.score?.toFixed(3)}</Tag>
                  <Text strong>{r.title}</Text>
                </Space>
                <div style={{ marginTop: 4, fontSize: 12, opacity: 0.7 }}>
                  {r.content}
                </div>
              </Card>
            ))}
          </div>
        )}
      </Card>

      {/* Runbook 列表 */}
      <Card
        size="small"
        title={`${t('kb.kbTitle')} (${runbooks.length} ${t('kb.entries')})`}
        extra={
          <Space>
            <Select
              placeholder={t('kb.filterStatus')}
              allowClear
              style={{ width: 120 }}
              value={filterStatus || undefined}
              onChange={(v) => setFilterStatus(v || '')}
              options={Object.entries(STATUS_KEYS).map(([k, v]) => ({ value: k, label: t(v as any) }))}
            />
            <Button icon={<ReloadOutlined />} onClick={() => { fetchRunbooks(); fetchStats() }} size="small">
              {t('kb.refresh')}
            </Button>
            <Button type="primary" icon={<PlusOutlined />} size="small"
              onClick={() => { setEditing(null); form.resetFields(); setModalOpen(true) }}>
              {t('kb.add')}
            </Button>
          </Space>
        }
      >
        {runbooks.length === 0 && !loading ? (
          <Empty description={t('kb.empty')} />
        ) : (
          <Table
            dataSource={runbooks}
            columns={columns}
            rowKey="id"
            loading={loading}
            size="small"
            pagination={{ pageSize: 15, size: 'small' }}
            scroll={{ x: 900 }}
          />
        )}
      </Card>

      {/* 新增/编辑 Modal */}
      <Modal
        title={editing ? t('kb.editRunbook') : t('kb.addRunbook')}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => { setModalOpen(false); form.resetFields() }}
        width={680}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label={t('kb.title')} rules={[{ required: true, message: t('kb.titleRequired') }]}>
            <Input placeholder={t('kb.titlePlaceholder')} />
          </Form.Item>
          <Form.Item name="content" label={t('kb.content')} rules={[{ required: true, message: t('kb.contentRequired') }]}>
            <TextArea
              placeholder={t('kb.contentPlaceholder')}
              rows={8}
            />
          </Form.Item>
          <Form.Item name="tags" label={t('kb.tagsLabel')}>
            <Input placeholder={t('kb.tagsPlaceholder')} />
          </Form.Item>
          {!editing && (
            <Form.Item name="status" label={t('kb.status')} initialValue="approved">
              <Select
                options={[
                  { value: 'approved', label: t('kb.approvedNow') },
                  { value: 'pending_review', label: t('kb.pendingReview') },
                ]}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  )
}

export default KnowledgeBase
