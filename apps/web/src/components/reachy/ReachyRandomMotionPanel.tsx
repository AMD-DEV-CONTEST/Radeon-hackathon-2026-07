/**
 * Random performance toggle — picks from official HF emotions + dances every 10s.
 */
import { Dices, Loader2 } from 'lucide-react'
import { Button } from '../ui/button'
import { useReachyRandomMotion } from '../../hooks/useReachyRandomMotion'

interface Props {
  daemonOnline: boolean
}

export function ReachyRandomMotionPanel({ daemonOnline }: Props) {
  const {
    active,
    loading,
    error,
    poolSize,
    currentMove,
    start,
    stop,
  } = useReachyRandomMotion(daemonOnline)

  return (
    <section className="rounded-md border border-white/10 bg-muted/20">
      <div className="flex items-center justify-between gap-2 border-b border-white/5 px-2.5 py-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-xs font-medium">
            <Dices className="h-3.5 w-3.5 text-violet-300" />
            随机表演
          </div>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            {active
              ? `每 10 秒随机播放${poolSize ? `（共 ${poolSize} 个）` : ''} · 切 Tab 或离开页面仍会继续`
              : '每 10 秒从官方表情 + 舞蹈库随机播放'}
          </p>
        </div>
        {active ? (
          <Button
            size="sm"
            variant="outline"
            className="h-7 shrink-0 border-red-500/40 text-red-200 hover:bg-red-500/10"
            onClick={stop}
          >
            停止
          </Button>
        ) : (
          <Button
            size="sm"
            className="h-7 shrink-0"
            disabled={!daemonOnline || loading}
            onClick={() => void start()}
          >
            {loading ? (
              <>
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                加载…
              </>
            ) : (
              '开始'
            )}
          </Button>
        )}
      </div>
      {(active && currentMove) || error ? (
        <div className="px-2.5 py-1.5 text-[11px]">
          {active && currentMove ? (
            <span className="text-muted-foreground">
              正在播放：<span className="font-medium text-foreground">{currentMove}</span>
            </span>
          ) : null}
          {error ? (
            <p className={active && currentMove ? 'mt-1 text-red-300' : 'text-red-300'}>{error}</p>
          ) : null}
        </div>
      ) : null}
      {!daemonOnline ? (
        <p className="border-t border-white/5 px-2.5 py-1.5 text-[10px] text-muted-foreground">
          请先启动机器人
        </p>
      ) : null}
    </section>
  )
}
