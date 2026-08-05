import { useEffect, useRef, useState, useCallback } from 'react'
import {
  Tree, Timeline, Card, Tag, Typography, Badge, Spin, Collapse,
  Empty, Descriptions, Statistic,
} from 'antd'
import {
  BulbOutlined, RobotOutlined, ToolOutlined, ApiOutlined,
  CheckCircleOutlined, ThunderboltOutlined, DashboardOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { wsManager } from '../websocket'
import { useI18n, type Lang } from '../i18n'

const { Text, Paragraph } = Typography

interface Session {
  id: string; parent_id: string | null; type: string
  status: string; trigger: string; started_at: number; ended_at: number
}
interface AgentEvent { type: string; session_id: string; kind: string; content: any }
interface HistEvent { seq: number; kind: string; content: any; ts: number }

const KIND_KEYS: Record<string, string> = {
  reasoning: 'agent.thinking',
  stream_reasoning: 'agent.thinkingNow',
  assistant: 'agent.response',
  stream_content: 'agent.responding',
  tool_call: 'agent.toolCall',
  tool_result: 'agent.result',
  user_input: 'agent.input',
  final_answer: 'agent.done',
  runbook_prompt: 'agent.learning',
}
const KIND_COLORS: Record<string, string> = {
  reasoning: 'purple', stream_reasoning: 'purple',
  assistant: 'blue', stream_content: 'blue',
  tool_call: 'orange', tool_result: 'green',
  user_input: 'default', final_answer: 'success', runbook_prompt: 'cyan',
}
const KIND_ICONS: Record<string, any> = {
  reasoning: <BulbOutlined />, stream_reasoning: <BulbOutlined />,
  assistant: <RobotOutlined />, stream_content: <RobotOutlined />,
  tool_call: <ToolOutlined />, tool_result: <ApiOutlined />,
  user_input: <ThunderboltOutlined />,
  final_answer: <CheckCircleOutlined />, runbook_prompt: <CheckCircleOutlined />,
}

const MD_KINDS = new Set(['reasoning', 'stream_reasoning', 'assistant', 'stream_content', 'final_answer', 'user_input', 'runbook_prompt'])
const TOOL_KINDS = new Set(['tool_call', 'tool_result'])


function fmtTime(ts: number, lang: Lang): string {
  return new Date(ts * 1000).toLocaleTimeString(lang === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })
}

function fmtDateTime(ts: number): string {
  const d = new Date(ts * 1000)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${mm}/${dd} ${hh}:${min}`
}

function extractCall(_name: string, args: any, t: (k: any) => string): string {
  if (!args) return ''
  const p: string[] = []
  if (args.service) p.push(args.service)
  if (args.node) p.push(args.node)
  if (args.metric) p.push(args.metric)
  if (args.filter) p.push(`${t('agent.filter')}=${args.filter}`)
  if (args.query) p.push(`"${args.query}"`)
  if (args.action) p.push(args.action)
  if (args.reason) p.push(`(${args.reason.slice(0, 80)})`)
  return p.join(' ')
}

function extractResult(_name: string, r: any, t: (k: any) => string): string {
  if (!r || typeof r !== 'object') return ''
  if (r.error) return `${t('agent.error')}: ${r.error}`
  if (r.overall_health) return `${t('agent.healthEq')}=${r.overall_health}, ${t('agent.rolesEq')}=${r.role_count ?? 0}`
  if (r.count !== undefined) return `${t('agent.alertsEq')}=${r.count}`
  if (r.total_errors !== undefined) return `${t('agent.errorsEq')}=${r.total_errors}, ${t('agent.nodesEq')}=${r.nodes_checked ?? 0}`
  if (r.matches !== undefined) return `${t('agent.matchesEq')}=${r.matches}`
  if (r.result) return `${t('agent.resultEq')}=${r.result}`
  if (r.command_id) return `${t('agent.commandEq')}=${r.command_id}, ${t('agent.resultEq')}=${r.result ?? '?'}`
  if (r.output) return (r.output as string).slice(0, 100).replace(/\n/g, ' ')
  if (r.nodes) return `${t('agent.nodesEq')}=${Object.keys(r.nodes).join(',')}`
  return JSON.stringify(r).slice(0, 100)
}

function AgentActivity() {
  const { t, lang } = useI18n()
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedSid, setSelectedSid] = useState('')
  const [selectedSession, setSelectedSession] = useState<Session | null>(null)
  const [events, setEvents] = useState<(HistEvent | AgentEvent)[]>([])
  const [clusterSnap, setClusterSnap] = useState<any>(null)
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(false)

  const scrollRef = useRef<HTMLDivElement>(null)
  const sessionsRef = useRef<Session[]>([])
  const selectedSidRef = useRef('')
  const atBottomRef = useRef(true)
  const autoScrollRef = useRef(false)

  sessionsRef.current = sessions
  selectedSidRef.current = selectedSid

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch('/api/sessions')
      const data: Session[] = await res.json()
      setSessions(data)
      if (data.length > 0 && !selectedSidRef.current) setSelectedSid(data[0].id)
    } catch (e) {
      console.error('fetchSessions failed:', e)
    }
  }, [])

  const fetchEvents = useCallback(async (sid: string) => {
    setLoading(true)
    try {
      const res = await fetch(`/api/sessions/${sid}/events`)
      const data: HistEvent[] = await res.json()
      setEvents(data.map(e => ({ ...e, session_id: sid, type: 'agent_event' })))
    } catch (e) {
      console.error('fetchEvents failed:', e)
      setEvents([])
    }
    setLoading(false)
  }, [])

  const fetchClusterSnap = useCallback(async () => {
    try {
      const res = await fetch('/api/cluster/snapshot')
      const data = await res.json()
      setClusterSnap(data)
    } catch (e) {
      console.error('fetchClusterSnap failed:', e)
    }
  }, [])

  useEffect(() => {
    fetchSessions()
    const t = setInterval(fetchSessions, 5000)
    return () => clearInterval(t)
  }, [fetchSessions])

  useEffect(() => {
    if (!selectedSid) return
    const s = sessionsRef.current.find(x => x.id === selectedSid)
    if (s?.type === 'master') { fetchClusterSnap(); setEvents([]) }
    else { fetchEvents(selectedSid) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSid])

  useEffect(() => {
    if (selectedSid) {
      const s = sessions.find(x => x.id === selectedSid)
      setSelectedSession(s || null)
    }
  }, [sessions, selectedSid])


  // WebSocket — 使用全局单例, 不在此处创建独立连接
  useEffect(() => {
    const unsubscribe = wsManager.subscribe((data) => {
      if (data.type === 'connection') {
        setConnected(data.status === 'connected')
        return
      }
      if (data.type !== 'agent_event') return

      const currentSid = selectedSidRef.current

      if (data.session_id !== currentSid) {
        if (data.kind === 'user_input') {
          fetchSessions()
          const current = sessionsRef.current.find(s => s.id === currentSid)
          if (!current || current.type === 'master' || current.ended_at) {
            setSelectedSid(data.session_id)
          }
        } else if (data.kind === 'final_answer') {
          fetchSessions()
        }
        return
      }

      // 流式 token: 实时合并到 events
      if (data.kind === 'stream_reasoning' || data.kind === 'stream_content') {
        setEvents(prev => {
          const last = prev[prev.length - 1] as any
          if (last && last.kind === data.kind) {
            return [...prev.slice(0, -1), {
              ...last,
              content: { text: (last.content?.text || '') + (data.content?.text || '') }
            }]
          }
          return [...prev, data]
        })
        autoScrollRef.current = true
        return
      }

      // 完整事件: 替换流式事件或追加
      if (data.kind === 'reasoning' || data.kind === 'assistant') {
        const streamKind = data.kind === 'reasoning' ? 'stream_reasoning' : 'stream_content'
        setEvents(prev => {
          const last = prev[prev.length - 1] as any
          if (last && last.kind === streamKind) {
            return [...prev.slice(0, -1), data]
          }
          return [...prev, data]
        })
        autoScrollRef.current = true
        return
      }

      // 其他事件: 直接追加
      setEvents(prev => [...prev, data])
      autoScrollRef.current = true

      if (data.kind === 'final_answer') {
        fetchSessions()
      }
    })

    return unsubscribe
  }, [fetchSessions])

  // 只在用户在底部时自动滚动
  useEffect(() => {
    if (autoScrollRef.current && atBottomRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
    autoScrollRef.current = false
  }, [events])

  const handleScroll = () => {
    if (scrollRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = scrollRef.current
      atBottomRef.current = scrollHeight - scrollTop - clientHeight < 80
    }
  }

  const roots = sessions.filter(s => !s.parent_id)
  const buildTree = (s: Session): any => {
    const children = sessions.filter(c => c.parent_id === s.id)
    const labels: Record<string, string> = { master: t('agent.master'), auto: t('agent.inspection'), fix: t('agent.fix'), chat: t('agent.chat') }
    const colors: Record<string, string> = { master: 'processing', auto: 'blue', fix: 'warning', chat: 'geekblue' }
    const latestMaster = sessions.find(x => x.type === 'master' && !x.ended_at)
    const isLatestMaster = s.type === 'master' && !s.ended_at && s.id === latestMaster?.id
    const isActiveTask = (s.type === 'auto' || s.type === 'fix' || s.type === 'chat') && !s.ended_at && s.parent_id === latestMaster?.id
    return {
      key: s.id,
      title: (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, width: 260 }}>
          <Tag color={colors[s.type]} style={{ margin: 0, fontSize: 11, flexShrink: 0 }}>{labels[s.type] || s.type}</Tag>
          <span style={{ fontSize: 11, color: '#94a3b8', whiteSpace: 'nowrap' }}>{fmtDateTime(s.started_at)}</span>
          {(isLatestMaster || isActiveTask) && <Badge status="processing" title={t('agent.inProgress')} />}
        </div>
      ),
      children: children.map(buildTree),
    }
  }
  const treeData = roots.map(buildTree)

  const renderClusterSnap = () => {
    if (!clusterSnap) return <Empty description={t('agent.noCluster')} />
    const services = clusterSnap.services || {}
    return (
      <div>
        <Card size="small" style={{ marginBottom: 12 }}>
          <Statistic
            title={t('agent.clusterHealth')}
            value={clusterSnap.overall_health || 'UNKNOWN'}
            prefix={<DashboardOutlined />}
            valueStyle={{ color: clusterSnap.overall_health === 'GOOD' ? '#22c55e' : '#ef4444' }}
          />
        </Card>
        <Card size="small" title={t('agent.serviceStatus')}>
          {Object.entries(services).map(([name, info]: [string, any]) => (
            <Descriptions key={name} size="small" column={3} bordered style={{ marginBottom: 8 }}
              items={[
                { key: 'name', label: t('agent.service'), children: name },
                { key: 'health', label: t('agent.health'), children: (
                  <Tag color={info.health === 'GOOD' ? 'success' : 'error'}>{info.health || 'UNKNOWN'}</Tag>
                )},
                { key: 'roles', label: t('agent.roles'), children: info.role_count || 0 },
              ]}
            />
          ))}
        </Card>
      </div>
    )
  }

  // 渲染所有事件
  const renderEvents = events

  return (
    <div style={{ display: 'flex', gap: 12, height: '100%', overflow: 'hidden', padding: 4 }}>
      <Card
        size="small"
        style={{ width: 320, flexShrink: 0, height: '100%', display: 'flex', flexDirection: 'column' }}
        styles={{ body: { flex: 1, overflow: 'hidden', minHeight: 0, padding: '8px 12px' } }}
        title={<Badge status={connected ? 'success' : 'default'} text={connected ? t('agent.live') : t('agent.offline')} />}
      >
        <div className="chat-session-list" style={{ height: '100%', overflow: 'auto' }}>
          {sessions.length === 0 ? <Empty description={t('agent.noSessions')} /> : (
            <Tree
              treeData={treeData}
              selectedKeys={selectedSid ? [selectedSid] : []}
              onSelect={(keys) => keys[0] && setSelectedSid(keys[0] as string)}
              defaultExpandAll
              showLine
              style={{ fontSize: 12 }}
            />
          )}
        </div>
      </Card>

      <Card
        size="small"
        style={{ flex: 1, minWidth: 0, height: '100%', display: 'flex', flexDirection: 'column' }}
        styles={{ body: { flex: 1, overflow: 'hidden', minHeight: 0, padding: 0 } }}
        title={selectedSession
          ? `${selectedSession.type === 'master' ? t('agent.master') : selectedSession.type === 'auto' ? t('agent.inspection') : selectedSession.type === 'fix' ? t('agent.fix') : t('agent.chat')} ${fmtTime(selectedSession.started_at, lang)}`
          : t('agent.selectSession')}
      >
        <div ref={scrollRef} onScroll={handleScroll} className="chat-msg-list" style={{ height: '100%', overflow: 'auto', padding: '8px 16px' }}>
          {selectedSession?.type === 'master' ? (
            renderClusterSnap()
          ) : loading ? (
            <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
          ) : events.length === 0 ? (
            <Empty description={t('agent.noEvents')} />
          ) : (
            <Timeline items={renderEvents.map((evt: any, i) => {
              const cfg_color = KIND_COLORS[evt.kind] || 'gray'
              const cfg_icon = KIND_ICONS[evt.kind] || null
              const cfg_label = t(KIND_KEYS[evt.kind] as any) || evt.kind
              const content = evt.content || {}
              const isMD = MD_KINDS.has(evt.kind)
              const isTool = TOOL_KINDS.has(evt.kind)
              let summary = ''
              if (evt.kind === 'tool_call')
                summary = `${content.name}(${extractCall(content.name, content.args || {}, t)})`
              else if (evt.kind === 'tool_result')
                summary = extractResult(content.name || '', content.result || content, t)
              else if (evt.kind === 'assistant') {
                // assistant 事件: 显示 text 或 tool_calls
                const text = content.text || ''
                const tools = content.tool_calls?.map((tc: any) => tc.name).join(', ') || ''
                summary = text.trim() || tools
              }
              else if (typeof content.text === 'string' && content.text.trim().length > 0) 
                summary = content.text
              else if (content.tool_calls?.length)
                summary = content.tool_calls.map((tc: any) => tc.name).join(', ')

              return {
                key: i, color: cfg_color as any, dot: cfg_icon,
                children: (
                  <div>
                    <div style={{ marginBottom: 4 }}>
                      <Tag color={cfg_color}>{cfg_label}</Tag>
                    </div>
                    {isMD ? (
                      <div className="markdown-body" style={{ fontSize: 13, lineHeight: 1.6 }}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{summary || ''}</ReactMarkdown>
                      </div>
                    ) : isTool ? (
                      <div>
                        <Paragraph style={{ margin: 0 }}>
                          <Text style={{ fontSize: 13 }}>{summary}</Text>
                        </Paragraph>
                        <Collapse ghost size="small" items={[{
                          key: 'json', label: t('agent.jsonDetail'),
                          children: (
                            <pre style={{ fontSize: 11, color: '#888', overflow: 'auto',
                              maxHeight: 280, background: '#0d1117',
                              padding: 10, borderRadius: 6 }}>
                              {JSON.stringify(content, null, 2)}
                            </pre>
                          )
                        }]} />
                      </div>
                    ) : (
                      <Text style={{ fontSize: 13 }}>{summary}</Text>
                    )}
                  </div>
                ),
              }
            })} />
          )}
        </div>
      </Card>
    </div>
  )
}

export default AgentActivity
