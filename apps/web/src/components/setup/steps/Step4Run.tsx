import { useEffect, useState } from 'react'
import { ArrowUpRight, CheckCircle2, Info, Play } from 'lucide-react'
import { Input } from '../../ui/input'
import { Button, buttonVariants } from '../../ui/button'
import { SetupStepCard } from '../SetupStepCard'
import { useSetup } from '../SetupProvider'
import { authJson } from '../../../lib/auth'

interface Recommendation {
  id: string
  name: string
  backend: string
  description: string
  requires_camera?: boolean
  requires_cloud?: boolean
  available?: boolean
  reason: string
  model_size_mb?: number
}

interface DatasetSummary {
  dataset_id: string
  frame_count: number | null
  has_images?: boolean
}

function framesToEpisodes(frames: number | null | undefined): number {
  if (!frames || frames <= 0) return 0
  return Math.max(1, Math.round(frames / 200))
}

function localFallback(hasCamera: boolean): Recommendation {
  return hasCamera
    ? {
        id: 'vision_mlp_baseline',
        name: 'Vision MLP (ResNet18 + MLP head)',
        backend: 'local',
        description: '本地视觉基线，可用于快速验证数据闭环。',
        requires_camera: true,
        reason: '已选择摄像头，优先推荐能使用图像的本地模型。',
      }
    : {
        id: 'mlp_baseline',
        name: 'MLP Baseline',
        backend: 'local',
        description: '本地关节数据基线。',
        reason: '未选择摄像头，推荐先跑关节数据基线。',
      }
}

export function Step4Run() {
  const { state, setLastModel, markComplete } = useSetup()
  const [draftModel, setDraftModel] = useState(state.lastModelKey ?? '')
  const [rec, setRec] = useState<Recommendation | null>(null)
  const [episodeCount, setEpisodeCount] = useState<number | null>(null)
  const [recLoading, setRecLoading] = useState(false)

  const datasetId = state.lastDatasetId ?? ''
  const modelKey = state.lastModelKey ?? ''
  const hasCamera = !!state.camera

  useEffect(() => {
    let cancelled = false
    setRecLoading(true)
    ;(async () => {
      let epCount = 0
      if (datasetId) {
        try {
          const r = await fetch('/api/datasets')
          if (r.ok) {
            const body = (await r.json()) as { items: DatasetSummary[] }
            const found = body.items.find((d) => d.dataset_id === datasetId)
            epCount = framesToEpisodes(found?.frame_count)
          }
        } catch {
          /* recommender still works without dataset metadata */
        }
      }
      if (cancelled) return
      setEpisodeCount(epCount || null)

      try {
        const qs = new URLSearchParams({ has_camera: String(hasCamera) })
        if (epCount) qs.set('episode_count', String(epCount))
        const body = await authJson<{ recommended: Recommendation }>(
          `/api/v1/trainings/algorithms/recommend?${qs.toString()}`,
        )
        if (!cancelled) setRec(body.recommended)
      } catch {
        if (!cancelled) setRec(localFallback(hasCamera))
      } finally {
        if (!cancelled) setRecLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [datasetId, hasCamera])

  const algo = rec?.id ?? (hasCamera ? 'vision_mlp_baseline' : 'mlp_baseline')
  const trainHref =
    datasetId.length > 0
      ? `/training?dataset_id=${encodeURIComponent(datasetId)}&algorithm=${algo}&from_setup=1`
      : '/training'
  const inferHref =
    modelKey.length > 0
      ? `/inference?model_key=${encodeURIComponent(modelKey)}&dataset_id=${encodeURIComponent(datasetId)}&from_setup=1`
      : '/inference'

  const saveModel = () => {
    const key = draftModel.trim()
    setLastModel(key.length > 0 ? key : null)
  }

  const unavailableCloud = rec?.backend === 'qualia' && rec.available === false

  return (
    <SetupStepCard
      stepId="run"
      title="训练并运行"
      description="用刚才录的数据训练一个模型。拿到模型后，直接进入推理页试运行。"
      hideNext
    >
      <div className="grid gap-4 text-sm">
        <div className="rounded-lg border border-[hsl(var(--primary))]/30 bg-[hsl(var(--primary))]/5 p-4 space-y-2">
          <div className="flex items-center gap-2">
            <Info className="h-4 w-4 text-[hsl(var(--primary))]" />
            <span className="text-xs font-semibold uppercase tracking-wider text-[hsl(var(--primary))]">
              推荐训练配置
            </span>
          </div>
          {recLoading && !rec ? (
            <div className="text-sm text-[hsl(var(--muted-foreground))]">正在选择合适算法…</div>
          ) : rec ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{rec.name}</span>
                <code className="font-mono text-[11px] text-[hsl(var(--muted-foreground))]">
                  {rec.id}
                </code>
                <span className="rounded-full border border-[hsl(var(--border))] px-2 py-0.5 text-[10px] text-[hsl(var(--muted-foreground))]">
                  {rec.backend === 'qualia' ? 'cloud' : 'local'}
                </span>
                {rec.requires_camera && (
                  <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">
                    camera
                  </span>
                )}
              </div>
              <p className="text-xs text-[hsl(var(--muted-foreground))]">{rec.reason}</p>
              {rec.description && (
                <p className="text-[11px] text-[hsl(var(--muted-foreground))]/80">
                  {rec.description}
                </p>
              )}
              {unavailableCloud && (
                <p className="text-[11px] text-amber-300">
                  云端训练需要先配置 Qualia token。你也可以在训练页切换成本地算法。
                </p>
              )}
            </>
          ) : null}
        </div>

        <div className="grid gap-3 rounded-lg border border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40 p-4">
          <div className="font-medium">1. 训练模型</div>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            会带上数据集 <code className="font-mono">{datasetId || '（先完成录制）'}</code>
            、推荐算法 <code className="font-mono">{algo}</code>
            {episodeCount ? `，约 ${episodeCount} 条 episode。` : '。'}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <a
              href={trainHref}
              className={buttonVariants({ variant: datasetId ? 'default' : 'outline' })}
              aria-disabled={!datasetId}
            >
              <ArrowUpRight className="h-4 w-4" />
              打开训练页
            </a>
            {!datasetId && (
              <span className="text-xs text-amber-300">先完成上一阶段录制，才能自动带入数据集。</span>
            )}
          </div>
        </div>

        <div className="grid gap-3 rounded-lg border border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40 p-4">
          <div className="font-medium">2. 运行技能</div>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            训练完成后，把模型 key 粘到这里。进入推理页时会自动预填模型和数据集。
          </p>
          <div className="flex gap-2">
            <Input
              value={draftModel}
              onChange={(e) => setDraftModel(e.target.value)}
              placeholder="例如 skill_abc123/v1 或 owner/model"
              className="font-mono"
            />
            <Button onClick={saveModel} variant={modelKey ? 'secondary' : 'default'}>
              <CheckCircle2 className="h-4 w-4" />
              保存
            </Button>
          </div>
          {modelKey && (
            <div className="flex flex-wrap items-center gap-3">
              <a href={inferHref} className={buttonVariants({ variant: 'default' })}>
                <Play className="h-4 w-4" />
                打开推理页
              </a>
              <Button
                variant={state.completed.run ? 'secondary' : 'outline'}
                onClick={() => markComplete('run', !state.completed.run)}
              >
                <CheckCircle2 className="h-4 w-4" />
                {state.completed.run ? '已完成，点击撤销' : '我已完成试运行'}
              </Button>
            </div>
          )}
          {!modelKey && (
            <span className="text-xs text-amber-300">保存模型 key 后，推理入口会打开。</span>
          )}
        </div>
      </div>
    </SetupStepCard>
  )
}
