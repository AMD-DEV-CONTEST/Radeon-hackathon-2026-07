/**
* LeKiwi handshake — three-stage data plan progress card + P2 closed loop.
*
* Visualizes the L1 / L2 / L3 data collection plan from
* ~/brainbot/lingbot_configs/handshake_data_plan.md (brought over from GB10).
* The user sees "how many more episodes until next generalization tier".
*
* P2 closed loop: when the user toggles "auto-continue" on, this card polls
* /api/lekiwi/handshake/plan every ~10s. When a new L-tier is reached, it
* calls /api/lekiwi/handshake/auto_continue to trigger
* norm_stats → 续训 → sync_model_to_remote 热加载 in the background, and
* shows the chain status (phase + logs).
*/
import { useCallback, useEffect, useRef, useState } from 'react'
import { CheckCircle2, Circle, Loader2, Zap, AlertCircle } from 'lucide-react'
import {
  getAutoContinueStatus,
  getHandshakePlan,
  handshakePhaseLabel,
  triggerAutoContinue,
  type LeKiwiHandshakeStatus,
} from '../../lib/lekiwiHandshakeApi'

export interface LeKiwiHandshakePlan {
  l1_target: number  // e.g. 20
  l2_target: number  // e.g. 50
  l3_target: number  // e.g. 100
  current_episodes: number
}

export const DEFAULT_LEKIWI_HANDSHAKE_PLAN: LeKiwiHandshakePlan = {
  l1_target: 20,
  l2_target: 50,
  l3_target: 100,
  current_episodes: 0,
}

interface StageInfo {
  id: 'L1' | 'L2' | 'L3'
  label: string
  description: string
  target: number
  reached: boolean
  in_progress: boolean
  progress: number  // 0..1
}

function computeStages(plan: LeKiwiHandshakePlan): StageInfo[] {
  const cur = plan.current_episodes
  const stages: Array<Omit<StageInfo, 'reached' | 'in_progress' | 'progress'>> = [
    {
      id: 'L1',
      label: 'L1 · 基础握手',
      description: '单人正面握手，固定距离。先让模型学会"伸手 → 握 → 松开"的基本动作。',
      target: plan.l1_target,
    },
    {
      id: 'L2',
      label: 'L2 · 变化泛化',
      description: '不同接近角度、不同手高度。让模型适应不同人的姿态。',
      target: plan.l2_target,
    },
    {
      id: 'L3',
      label: 'L3 · 真实场景',
      description: '人群环境、动态干扰、噪声。让模型在真实场景里能跑。',
      target: plan.l3_target,
    },
  ]
  return stages.map((s, i) => {
    const prevTarget = i === 0 ? 0 : stages[i - 1].target
    const reached = cur >= s.target
    const in_progress = !reached && cur >= prevTarget
    const progress = reached ? 1 : Math.max(0, Math.min(1, (cur - prevTarget) / (s.target - prevTarget)))
    return { ...s, reached, in_progress, progress }
  })
}

interface Props {
  plan: LeKiwiHandshakePlan
  loading?: boolean
  /** LeRobot repo_id to read episode count from (e.g. "local/lekiwi-handshake-20260731"). */
  repoId?: string
  /** Optional: pass a saved API token to submit training on behalf of the user. */
  apiToken?: string
  /** Optional: RemoteComputeNode id for sync_model_to_remote. */
  nodeId?: string
}

export function LeKiwiHandshakeProgressCard({
  plan,
  loading = false,
  repoId,
  apiToken,
  nodeId,
}: Props) {
  const [stages, setStages] = useState<StageInfo[]>(() => computeStages(plan))
  const [autoOn, setAutoOn] = useState(false)
  const [livePlan, setLivePlan] = useState<LeKiwiHandshakePlan>(plan)
  const [chainStatus, setChainStatus] = useState<LeKiwiHandshakeStatus | null>(null)
  const [chainError, setChainError] = useState<string | null>(null)
  const [triggering, setTriggering] = useState(false)
  const lastTierRef = useRef<string | null>(null)

  useEffect(() => {
    setStages(computeStages(plan))
    setLivePlan(plan)
  }, [plan])

  // Poll handshake plan + chain status when auto-continue is on.
  useEffect(() => {
    if (!autoOn || !repoId) return
    let cancelled = false

    const tick = async () => {
      try {
        const p = await getHandshakePlan({
          repoId: repoId!,
          l1Target: plan.l1_target,
          l2Target: plan.l2_target,
          l3Target: plan.l3_target,
        })
        if (cancelled) return
        setLivePlan({
          l1_target: p.l1_target,
          l2_target: p.l2_target,
          l3_target: p.l3_target,
          current_episodes: p.current_episodes,
        })
        setStages(computeStages({
          l1_target: p.l1_target,
          l2_target: p.l2_target,
          l3_target: p.l3_target,
          current_episodes: p.current_episodes,
        }))

        // If a new tier was just reached, trigger the chain (once).
        const tier = p.tier_reached
        if (tier && tier !== lastTierRef.current) {
          lastTierRef.current = tier
          setTriggering(true)
          setChainError(null)
          try {
            const r = await triggerAutoContinue({
              repo_id: repoId!,
              l1_target: p.l1_target,
              l2_target: p.l2_target,
              l3_target: p.l3_target,
              api_token: apiToken,
              node_id: nodeId,
              task_prompt: 'lekiwi handshake',
            })
            if (!r.ok) setChainError(r.error || '触发失败')
          } catch (e) {
            setChainError(e instanceof Error ? e.message : '触发失败')
          } finally {
            setTriggering(false)
          }
        }
      } catch {
        // ignore — will retry next tick
      }

      try {
        const s = await getAutoContinueStatus()
        if (!cancelled) setChainStatus(s)
      } catch {
        /* ignore */
      }
    }

    void tick()
    const t = setInterval(tick, 10_000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [autoOn, repoId, plan.l1_target, plan.l2_target, plan.l3_target, apiToken, nodeId])

  // Also poll chain status when there's an active chain even if autoOn is off.
  useEffect(() => {
    if (autoOn || !chainStatus?.running) return
    let cancelled = false
    const t = setInterval(async () => {
      try {
        const s = await getAutoContinueStatus()
        if (!cancelled) setChainStatus(s)
      } catch {
        /* ignore */
      }
    }, 5_000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [autoOn, chainStatus?.running])

  const nextStage = stages.find((s) => !s.reached)
  const remaining = nextStage ? nextStage.target - livePlan.current_episodes : 0
  const phaseLabel = handshakePhaseLabel(chainStatus?.phase)
  const chainRunning = !!chainStatus?.running
  const chainFinished = chainStatus?.finished === true
  const chainHasError = chainStatus?.phase === 'error' || !!chainError

  const onToggleAuto = useCallback(() => {
    setAutoOn((v) => !v)
    setChainError(null)
  }, [])

  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-950/10 px-4 py-3 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-amber-200">LeKiwi 握手 · 数据反哺计划</p>
          <p className="text-[11px] text-amber-100/70 mt-0.5">
            三段式采集：基础 → 泛化 → 真实场景。每达到一层，模型在新一层上能跑得更稳。
          </p>
        </div>
        {loading ? <Loader2 className="h-4 w-4 animate-spin text-amber-300" /> : null}
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        {stages.map((s) => (
          <div
            key={s.id}
            className={
              'rounded-md border px-3 py-2 ' +
              (s.reached
                ? 'border-emerald-500/40 bg-emerald-950/20'
                : s.in_progress
                  ? 'border-amber-500/40 bg-amber-950/30'
                  : 'border-white/10 bg-black/20 opacity-70')
            }
          >
            <div className="flex items-center gap-1.5">
              {s.reached ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
              ) : s.in_progress ? (
                <Loader2 className="h-3.5 w-3.5 text-amber-400 animate-spin" />
              ) : (
                <Circle className="h-3.5 w-3.5 text-muted-foreground" />
              )}
              <span className="text-xs font-medium">{s.label}</span>
            </div>
            <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">{s.description}</p>
            <div className="mt-2 flex items-center justify-between text-[10px]">
              <span className="text-muted-foreground">
                {Math.min(livePlan.current_episodes, s.target)}/{s.target} 集
              </span>
              <span className={s.reached ? 'text-emerald-300' : s.in_progress ? 'text-amber-300' : 'text-muted-foreground'}>
                {Math.round(s.progress * 100)}%
              </span>
            </div>
            <div className="mt-1 h-1 w-full rounded-full bg-black/40 overflow-hidden">
              <div
                className={
                  'h-full rounded-full ' +
                  (s.reached ? 'bg-emerald-500' : s.in_progress ? 'bg-amber-500' : 'bg-white/20')
                }
                style={{ width: `${Math.round(s.progress * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      <div className="text-[11px] text-amber-100/80">
        {nextStage ? (
          <>
            当前 <strong className="text-amber-200">{livePlan.current_episodes}</strong> 集 ·
            距离 <strong className="text-amber-200">{nextStage.label}</strong> 还差{' '}
            <strong className="text-amber-200">{remaining}</strong> 集
          </>
        ) : (
          <span className="text-emerald-300">✓ 三段计划全部完成。可以开始训练生产级模型了。</span>
        )}
      </div>

      {/* P2 closed-loop toggle */}
      <div className="border-t border-amber-500/20 pt-3 space-y-2">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-medium text-amber-100 flex items-center gap-1.5">
              <Zap className="h-3.5 w-3.5" />
              自动闭环
            </p>
            <p className="text-[10px] text-amber-100/70 mt-0.5 leading-relaxed">
              达到下一层时自动触发：算 norm_stats → 续训 → sync 到算力节点热加载。
              {!repoId ? (
                <span className="text-amber-300"> 需要数据集 ID 才能开启。</span>
              ) : null}
            </p>
          </div>
          <button
            type="button"
            disabled={!repoId || triggering}
            onClick={onToggleAuto}
            className={
              'relative inline-flex h-6 w-11 items-center rounded-full transition disabled:opacity-40 ' +
              (autoOn ? 'bg-amber-500' : 'bg-white/15')
            }
            title={repoId ? '开启 / 关闭自动闭环' : '需要数据集 ID'}
          >
            <span
              className={
                'inline-block h-5 w-5 transform rounded-full bg-white shadow transition ' +
                (autoOn ? 'translate-x-5' : 'translate-x-0.5')
              }
            />
          </button>
        </div>

        {chainStatus?.phase && chainStatus.phase !== 'idle' ? (
          <div
            className={
              'rounded-md border px-3 py-2 text-[11px] ' +
              (chainHasError
                ? 'border-red-500/40 bg-red-950/20 text-red-200'
                : chainFinished
                  ? 'border-emerald-500/40 bg-emerald-950/20 text-emerald-200'
                  : 'border-sky-500/40 bg-sky-950/20 text-sky-200')
            }
          >
            <div className="flex items-center gap-1.5">
              {chainRunning ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : chainHasError ? (
                <AlertCircle className="h-3 w-3" />
              ) : (
                <CheckCircle2 className="h-3 w-3" />
              )}
              <span className="font-medium">{phaseLabel}</span>
              {chainStatus.tier ? (
                <span className="ml-1 rounded bg-white/10 px-1.5 py-0.5 text-[10px]">
                  tier: {chainStatus.tier}
                </span>
              ) : null}
            </div>
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] text-muted-foreground">
              <dt>norm_stats</dt>
              <dd className={chainStatus.norm_stats_ok ? 'text-emerald-300' : 'text-amber-300'}>
                {chainStatus.norm_stats_ok === undefined ? '—' : chainStatus.norm_stats_ok ? '✓' : '✗'}
              </dd>
              <dt>train</dt>
              <dd className={chainStatus.train_ok ? 'text-emerald-300' : 'text-amber-300'}>
                {chainStatus.train_ok === undefined
                  ? '—'
                  : chainStatus.train_ok
                    ? `✓ ${chainStatus.train_job_id ?? ''}`
                    : '✗'}
              </dd>
              <dt>sync</dt>
              <dd className={chainStatus.sync_ok ? 'text-emerald-300' : 'text-amber-300'}>
                {chainStatus.sync_ok === undefined ? '—' : chainStatus.sync_ok ? '✓' : '✗'}
              </dd>
            </dl>
            {chainError ? (
              <p className="mt-1.5 text-[10px] text-red-300">{chainError}</p>
            ) : null}
            {chainStatus?.train_log ? (
              <p className="mt-1.5 text-[10px] text-muted-foreground break-all">
                {chainStatus.train_log.slice(0, 200)}
              </p>
            ) : null}
            {chainStatus?.sync_log ? (
              <p className="mt-1 text-[10px] text-muted-foreground break-all">
                {chainStatus.sync_log.slice(0, 200)}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}
