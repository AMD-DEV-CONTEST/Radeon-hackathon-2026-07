import { AlertTriangle, Loader2, ScanLine } from 'lucide-react'
import { Button } from '../ui/button'
import type { B601Alignment } from '../../lib/b601Api'

interface Props {
  alignment: B601Alignment | null
  checking?: boolean
  checkingHint?: string | null
  onRecheck?: () => void
  onForceStart?: () => void
  forceBusy?: boolean
}

export function B601AlignmentPanel({
  alignment,
  checking = false,
  checkingHint,
  onRecheck,
  onForceStart,
  forceBusy,
}: Props) {
  if (checking) {
    return (
      <div className="rounded-md border border-sky-500/35 bg-sky-500/10 px-3 py-3 text-xs text-sky-100 space-y-2">
        <div className="flex items-center gap-2 font-medium">
          <Loader2 className="h-4 w-4 animate-spin shrink-0" />
          正在检查对齐（约 15–30 秒，请勿重复点击）
        </div>
        <ol className="list-decimal list-inside space-y-0.5 text-sky-200/85">
          <li>准备 CAN 总线（独占访问，避免与其他操作冲突）</li>
          <li>读取从臂 7 个关节角度</li>
          <li>读取主臂 USB 姿态并对比</li>
        </ol>
        {checkingHint && <p className="text-sky-300/90">{checkingHint}</p>}
      </div>
    )
  }

  if (!alignment) return null

  if (alignment.skipped) {
    return (
      <div className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-100">
        <div className="font-medium">暂时无法完成对齐检查</div>
        <p>{alignment.skip_reason ?? '读不到主从臂当前角度'}</p>
        <p className="text-amber-200/80">
          这不影响遥操 — 请直接点<strong className="font-normal">「开始遥操」</strong>，官方程序会自行连接从臂。启动后请先缓慢试主臂。
        </p>
        <div className="flex flex-wrap gap-2 pt-1">
          {onRecheck && (
            <Button type="button" size="sm" variant="outline" disabled={checking} onClick={onRecheck}>
              <ScanLine className="mr-1 h-3 w-3" />
              重新检查
            </Button>
          )}
        </div>
      </div>
    )
  }

  if (alignment.ok) {
    return (
      <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100">
        主从臂姿态已对齐（容差 ±{alignment.tolerance_deg}°），可以安全启动遥操。
      </div>
    )
  }

  return (
    <div className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-100">
      <div className="flex items-center gap-2 font-medium">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        主从臂姿态不一致 — 现在启动从臂可能猛窜
      </div>
      <p className="leading-relaxed text-amber-200/90">
        请用手把<strong className="font-normal">主臂</strong>调到接近从臂，再点「重新检查」。
      </p>
      <ul className="space-y-1">
        {alignment.mismatches.map((m) => (
          <li key={m.motor} className="rounded border border-amber-500/20 bg-black/20 px-2 py-1">
            <span className="font-medium">{m.label}</span>
            {' — '}
            <span className="font-mono tabular-nums">
              {m.delta_deg > 0 ? '+' : ''}
              {m.delta_deg.toFixed(1)}°
            </span>
            {' · '}
            {m.hint}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2 pt-1">
        {onRecheck && (
          <Button type="button" size="sm" variant="outline" disabled={checking} onClick={onRecheck}>
            {checking ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <ScanLine className="mr-1 h-3 w-3" />}
            重新检查
          </Button>
        )}
        {onForceStart && (
          <Button type="button" size="sm" variant="destructive" disabled={forceBusy} onClick={onForceStart}>
            我了解风险，强制启动
          </Button>
        )}
      </div>
    </div>
  )
}
