import { useEffect } from 'react'
import type { StageState, StageName } from './StagePipeline'

const STREAMING_BASE = import.meta.env.VITE_STREAMING_URL ?? 'http://111.228.42.18:8001'

interface SessionEvent {
  type?: string
  event_type?: string
  payload: Record<string, unknown>
  agent_id?: string
  timestamp?: string
  created_at?: string
}

interface GatewayHealth {
  sessions?: Array<{
    session_id: string
    status: string
    participants?: string[]
    connections?: number
  }>
}

export function useSessionStage(
  setStages: (s: StageState[]) => void,
  setCurrentStage: (s: StageName | null) => void,
) {
  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const healthResp = await fetch(`${STREAMING_BASE}/health`)
        if (!healthResp.ok) return
        const health = await healthResp.json() as GatewayHealth
        const sessions = health.sessions ?? []
        const latestSessionId = sessions[sessions.length - 1]?.session_id
        if (!latestSessionId) return

        const eventsResp = await fetch(`${STREAMING_BASE}/sessions/${latestSessionId}/events`)
        if (!eventsResp.ok) return
        const events = await eventsResp.json() as SessionEvent[]
        if (cancelled) return

        const stageMap: Record<string, Partial<StageState>> = {
          '论证': { name: '论证', round: 0, maxRounds: 2, status: 'pending', participants: [], deliverables: [{ label: '署名意见', done: false }] },
          '决策': { name: '决策', round: 0, maxRounds: 1, status: 'pending', participants: [], deliverables: [{ label: '决策文档', done: false }] },
          '计划': { name: '计划', round: 0, maxRounds: 1, status: 'pending', participants: [], deliverables: [{ label: '行动计划', done: false }, { label: 'Handoff', done: false }] },
          '实施': { name: '实施', round: 0, maxRounds: 5, status: 'pending', participants: [], deliverables: [{ label: '代码', done: false }, { label: '测试', done: false }] },
          '验收': { name: '验收', round: 0, maxRounds: 1, status: 'pending', participants: [], deliverables: [{ label: '老板确认', done: false }] },
        }

        const stageOrder: StageName[] = ['论证', '决策', '计划', '实施', '验收']
        let currentStageIdx = -1

        for (const event of events) {
          const payload = event.payload || {}
          const stage = payload.stage as string | undefined
          if (!stage || !stageMap[stage]) continue

          const s = stageMap[stage]
          const from = (payload.from as string | undefined) ?? event.agent_id

          if (from && !s.participants?.find(p => p.name === from)) {
            s.participants = [...(s.participants || []), { name: from, status: 'done' }]
          }

          if (payload.status === 'done') {
            s.status = 'done'
            if (s.deliverables) s.deliverables.forEach(d => d.done = true)
            const idx = stageOrder.indexOf(stage as StageName)
            if (idx > currentStageIdx) currentStageIdx = idx
          } else if (payload.status === 'active' || payload.status === 'in_progress'
            || (payload.event_type as string | undefined) === 'session_message'
            || event.type === 'session_message') {
            s.status = 'active'
            if (s.round !== undefined) {
              s.round = Math.max(s.round || 1, Number(payload.round ?? payload.stage_round) || 1)
            }
            const idx = stageOrder.indexOf(stage as StageName)
            if (idx > currentStageIdx) currentStageIdx = idx
          }
        }

        const stages = stageOrder.map(name => stageMap[name]) as StageState[]
        setStages(stages)

        if (currentStageIdx >= 0) {
          setCurrentStage(stageOrder[currentStageIdx])
        } else if (stages.some(s => s.status === 'active')) {
          setCurrentStage(stages.find(s => s.status === 'active')!.name)
        }
      } catch {
        // Silently fail — no session data yet
      }
    }

    load()
    const timer = setInterval(load, 5000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [setCurrentStage, setStages])
}
