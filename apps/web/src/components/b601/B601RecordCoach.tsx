/**
 * Large, glanceable coach during B601 recording — episode index, phase,
 * remaining seconds, and a short 3-2-1 “get ready” before each take.
 */
import { Loader2 } from 'lucide-react'
import { cn } from '../../lib/utils'

export type RecordPhase =
  | 'starting'
  | 'recording'
  | 'resetting'
  | 'saving'
  | 'done'
  | 'error'
  | 'idle'
  | string
  | null
  | undefined

interface Props {
  running: boolean
  phase: RecordPhase
  episode: number
  total: number
  /** Seconds elapsed in current recording/reset phase (client clock preferred). */
  phaseElapsedS: number
  phaseTargetS: number | null
  phaseOvertime?: boolean
  hint?: string | null
}

function formatMmSs(s: number) {
  const n = Math.max(0, Math.floor(s))
  return `${String(Math.floor(n / 60)).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}`
}

const PREP_S = 3

export function B601RecordCoach({
  running,
  phase,
  episode,
  total,
  phaseElapsedS,
  phaseTargetS,
  phaseOvertime,
  hint,
}: Props) {
  if (!running && phase !== 'done' && phase !== 'error') return null

  const remaining =
    phaseTargetS != null ? Math.max(0, phaseTargetS - phaseElapsedS) : null
  const progress =
    phaseTargetS != null && phaseTargetS > 0
      ? Math.min(100, (phaseElapsedS / phaseTargetS) * 100)
      : null

  const inPrep = phase === 'recording' && phaseElapsedS < PREP_S
  const prepCount = inPrep ? Math.max(1, PREP_S - Math.floor(phaseElapsedS)) : null

  let title = '采集'
  let subtitle = hint || ''
  let accent = 'border-white/15 bg-black/40 text-foreground'
  let mega: string | null = null
  let megaLabel: string | null = null

  if (phase === 'starting') {
    title = '请准备'
    subtitle = '正在连接主臂 / 从臂 / 相机… 马上开始'
    accent = 'border-violet-500/50 bg-violet-950/70 text-violet-50'
    mega = '…'
    megaLabel = '启动中'
  } else if (phase === 'recording' && inPrep) {
    title = '请准备'
    subtitle = `正在录第 ${episode > 0 ? episode : '?'} 条 — 握好主臂，摆好起点`
    accent = 'border-amber-400/60 bg-amber-950/80 text-amber-50'
    mega = String(prepCount)
    megaLabel = '倒计时'
  } else if (phase === 'recording') {
    title = '请开始采集'
    subtitle = `正在录第 ${episode > 0 ? episode : '?'} / ${total > 0 ? total : '?'} 条 · 用主臂完整示范`
    accent = 'border-sky-400/60 bg-sky-950/85 text-sky-50'
    mega = remaining != null ? formatMmSs(remaining) : formatMmSs(phaseElapsedS)
    megaLabel = remaining != null ? '本条剩余' : '已录'
  } else if (phase === 'resetting') {
    if (phaseElapsedS < 1.2) {
      title = '复位开始'
      subtitle = `第 ${episode > 0 ? episode : '?'} 条已录完 · 把场景摆回起点`
      accent = 'border-amber-400/60 bg-amber-950/85 text-amber-50'
      mega = remaining != null ? String(Math.ceil(remaining)) : '!'
      megaLabel = '复位秒数'
    } else if (remaining != null && remaining <= 2 && !phaseOvertime) {
      title = '复位即将结束'
      subtitle = `第 ${episode > 0 ? episode : '?'} 条复位 · 摆好了可点「复位完成·下一条」`
      accent = 'border-orange-400/60 bg-orange-950/85 text-orange-50'
      mega = String(Math.ceil(remaining))
      megaLabel = '还剩'
    } else if (phaseOvertime || (remaining != null && remaining <= 0)) {
      title = '复位结束'
      subtitle = `第 ${episode > 0 ? episode : '?'} 条 · 正在进入保存…`
      accent = 'border-amber-500/40 bg-amber-950/60 text-amber-100'
      mega = '0'
      megaLabel = '到点'
    } else {
      title = '复位中'
      subtitle = `第 ${episode > 0 ? episode : '?'} 条复位 · 摆好后可提前点「下一条」`
      accent = 'border-amber-400/50 bg-amber-950/75 text-amber-50'
      mega = remaining != null ? formatMmSs(remaining) : formatMmSs(phaseElapsedS)
      megaLabel = remaining != null ? '复位剩余' : '已复位'
    }
  } else if (phase === 'saving') {
    title = '保存中'
    subtitle =
      episode > 0
        ? `正在保存第 ${episode}${total > 0 ? ` / ${total}` : ''} 条（刚录完的这一条），请勿拔线`
        : '正在写入视频 / parquet，请稍等，不要拔线'
    accent = 'border-fuchsia-400/50 bg-fuchsia-950/80 text-fuchsia-50'
    mega = null
    megaLabel = null
  } else if (phase === 'done') {
    title = '采集完成'
    subtitle = `共完成 ${episode > 0 ? episode : total > 0 ? total : '?'} 条 · 可预览或去训练`
    accent = 'border-emerald-400/50 bg-emerald-950/80 text-emerald-50'
    mega = '✓'
    megaLabel = '完成'
  } else if (phase === 'error') {
    title = '出错了'
    subtitle = hint || '请看下方日志，修好后重新开始采集'
    accent = 'border-rose-500/50 bg-rose-950/80 text-rose-50'
    mega = '!'
    megaLabel = '异常'
  }

  // Between takes: keep「当前条」= the one just finished (being saved), mention next separately.
  if (phase === 'saving' && episode > 0 && total > 0 && episode < total) {
    subtitle = `正在保存第 ${episode} 条（刚录完）· 保存后才开始第 ${episode + 1} 条`
  } else if (phase === 'saving' && episode > 0 && total > 0 && episode >= total) {
    subtitle = `正在保存第 ${episode} 条（最后一条）· 保存完即全部完成`
  }

  return (
    <div
      className={cn(
        'sticky top-0 z-20 overflow-hidden rounded-xl border-2 px-4 py-4 shadow-lg backdrop-blur-sm',
        accent,
      )}
      role="status"
      aria-live="polite"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <p className="text-[11px] font-medium uppercase tracking-wider opacity-80">
            采集教练 · 一眼看状态
          </p>
          <h3 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h3>
          <p className="text-sm leading-relaxed opacity-90">{subtitle}</p>
        </div>
        <div className="shrink-0 rounded-lg border border-white/15 bg-black/35 px-3 py-2 text-right">
          <p className="text-[10px] opacity-70">
            {phase === 'saving' ? '正在保存第' : phase === 'resetting' ? '刚录完第' : '正在录第'}
          </p>
          <p className="font-mono text-3xl font-bold tabular-nums leading-none">
            {episode > 0 ? episode : '—'}
            <span className="mx-1 text-lg font-normal opacity-50">/</span>
            {total > 0 ? total : '—'}
          </p>
          <p className="mt-1 text-[10px] opacity-60">条（当前，不是下一条）</p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-4">
        {phase === 'saving' ? (
          <div className="flex items-center gap-3">
            <Loader2 className="h-12 w-12 animate-spin opacity-90" />
            <div>
              <p className="text-lg font-semibold">
                {episode > 0 ? `正在保存第 ${episode} 条…` : '保存中…'}
              </p>
              <p className="text-xs opacity-80">
                {episode > 0 && total > 0 && episode < total
                  ? `这是刚录完的第 ${episode} 条；保存完才会开第 ${episode + 1} 条`
                  : '双路 AV1 写盘中，请勿拔线'}
              </p>
            </div>
          </div>
        ) : mega != null ? (
          <div>
            {megaLabel && <p className="mb-0.5 text-[11px] opacity-70">{megaLabel}</p>}
            <p
              className={cn(
                'font-mono font-bold tabular-nums leading-none tracking-tight',
                inPrep || (phase === 'resetting' && remaining != null && remaining <= 2)
                  ? 'text-6xl sm:text-7xl'
                  : 'text-5xl sm:text-6xl',
              )}
            >
              {mega}
            </p>
          </div>
        ) : null}

        {(phase === 'recording' || phase === 'resetting') && progress != null && (
          <div className="min-w-[140px] flex-1 pb-1">
            <div className="mb-1 flex justify-between text-[11px] opacity-75">
              <span>{phase === 'recording' ? '本条进度' : '复位进度'}</span>
              <span className="font-mono tabular-nums">
                {formatMmSs(phaseElapsedS)} / {formatMmSs(phaseTargetS ?? 0)}
              </span>
            </div>
            <div className="h-3 overflow-hidden rounded-full bg-black/40">
              <div
                className={cn(
                  'h-full transition-all duration-300',
                  phase === 'recording' ? 'bg-sky-400' : 'bg-amber-400',
                )}
                style={{ width: `${progress}%` }}
              />
            </div>
            {phaseOvertime && (
              <p className="mt-1 text-[11px] opacity-80">
                {phase === 'recording' ? '已到点 · 正在进复位…' : '复位已到点 · 正在保存或开下一条…'}
              </p>
            )}
          </div>
        )}
      </div>

      {phase === 'recording' && !inPrep && (
        <p className="mt-3 text-[11px] opacity-75">
          示范几秒后再点跳过；刚开录就跳过容易空 episode。
        </p>
      )}
    </div>
  )
}
