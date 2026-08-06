import { useState } from 'react'
import { CheckCircle2, Clock3, Loader2, ChevronRight, Users, FileText } from 'lucide-react'

export type StageName = '论证' | '决策' | '计划' | '实施' | '验收'

export interface StageState {
  name: StageName
  round: number
  maxRounds: number
  status: 'pending' | 'active' | 'done'
  participants: { name: string; status: 'idle' | 'working' | 'done' }[]
  deliverables: { label: string; done: boolean }[]
}

interface StagePipelineProps {
  stages: StageState[]
  currentStage: StageName | null
  onStageClick?: (stage: StageName) => void
}

const stageColors: Record<string, string> = {
  pending: '#334155',
  active: '#3b82f6',
  done: '#22c55e',
}

export function StagePipeline({ stages, currentStage, onStageClick }: StagePipelineProps) {
  const [expandedStage, setExpandedStage] = useState<StageName | null>(null)

  return (
    <div className="stage-pipeline-wrapper">
      <div className="pipeline-header">
        <span>工作流看板</span>
        <span className="pipeline-subtitle">Leader 操盘 · 手动推进阶段</span>
      </div>
      <div className="stage-pipeline">
        {stages.map((stage, i) => {
          const isActive = stage.name === currentStage
          const isDone = stage.status === 'done'
          const color = isActive ? stageColors.active : isDone ? stageColors.done : stageColors.pending
          const doneCount = stage.participants.filter(p => p.status === 'done').length

          return (
            <div key={stage.name} className="stage-item-group">
              <div
                className={`stage-node ${isActive ? 'active' : ''} ${isDone ? 'done' : ''}`}
                style={{ borderColor: color }}
                onClick={() => {
                  onStageClick?.(stage.name)
                  setExpandedStage(expandedStage === stage.name ? null : stage.name)
                }}
              >
                <div className="stage-icon" style={{ background: color }}>
                  {isDone ? <CheckCircle2 size={16} color="#fff" /> : isActive ? <Loader2 size={16} color="#fff" className="spin" /> : <Clock3 size={16} color="#94a3b8" />}
                </div>
                <div className="stage-info">
                  <div className="stage-name">{stage.name}</div>
                  <div className="stage-rounds">{stage.round}/{stage.maxRounds}轮</div>
                </div>
                <div className="stage-participant-count">
                  <Users size={12} /> {doneCount}/{stage.participants.length}
                </div>
              </div>
              {i < stages.length - 1 && (
                <ChevronRight size={16} className="stage-arrow" color={isDone ? '#22c55e' : '#334155'} />
              )}
            </div>
          )
        })}
      </div>

      {expandedStage && (() => {
        const stage = stages.find(s => s.name === expandedStage)
        if (!stage) return null
        return (
          <div className="stage-detail">
            <div className="stage-detail-header">
              <h4>{stage.name}阶段 · 第 {stage.round}/{stage.maxRounds} 轮</h4>
            </div>
            <div className="stage-detail-body">
              <div className="detail-section">
                <div className="detail-label"><Users size={14} /> 参与者</div>
                {stage.participants.map(p => (
                  <div key={p.name} className={`participant-row ${p.status}`}>
                    <span className="participant-name">{p.name}</span>
                    <span className="participant-status">
                      {p.status === 'done' ? '✅' : p.status === 'working' ? '🔄' : '⏳'}
                    </span>
                  </div>
                ))}
              </div>
              <div className="detail-section">
                <div className="detail-label"><FileText size={14} /> 交付物</div>
                {stage.deliverables.map(d => (
                  <div key={d.label} className={`deliverable-row ${d.done ? 'done' : ''}`}>
                    {d.done ? '✅' : '⏳'} {d.label}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
