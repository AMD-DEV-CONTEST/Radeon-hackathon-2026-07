import { Loader2, RefreshCw, Wrench } from 'lucide-react'
import { Button } from '../ui/button'

interface Props {
  onRecover: () => void
  onDisable: () => void
  onCalibrateStart: (target: 'follower' | 'leader') => void
  onCalibrateContinue: () => void
  onCalibrateStop: () => void
  calibrateRunning: boolean
  calibrateTarget?: string | null
  calibrateLog?: string[]
  busy: boolean
}

/** 折叠在侧栏底部 — 新手日常不需要打开。 */
export function B601AdvancedDrawer({
  onRecover,
  onDisable,
  onCalibrateStart,
  onCalibrateContinue,
  onCalibrateStop,
  calibrateRunning,
  calibrateTarget,
  calibrateLog = [],
  busy,
}: Props) {
  return (
    <div className="space-y-3 text-xs">
      <p className="font-medium text-foreground/90">故障恢复</p>
      <p className="text-muted-foreground leading-relaxed">
        从臂 fault、卡死、或需要重新标定时才用。日常遥操、手推漂浮不必打开此处。
      </p>
      <Button size="sm" variant="outline" className="w-full" onClick={onRecover} disabled={busy}>
        {busy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <RefreshCw className="mr-1 h-3 w-3" />}
        唤醒从臂
      </Button>
      <Button size="sm" variant="outline" className="w-full" onClick={onDisable} disabled={busy}>
        从臂卸力（可手推）
      </Button>

      <div className="rounded-md border border-white/10 bg-black/20 p-2 space-y-2">
        <div className="flex items-center gap-1 font-medium text-foreground/80">
          <Wrench className="h-3 w-3" />
          标定（工程师）
        </div>
        <p className="text-muted-foreground leading-relaxed">
          新手请用上方「标定 ID」面板的下拉框；此处仅在需要重跑{' '}
          <code className="text-[10px]">lerobot-calibrate</code> 时使用，按终端提示操作。
        </p>
        {!calibrateRunning ? (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => onCalibrateStart('follower')} disabled={busy}>
              校准从臂
            </Button>
            <Button size="sm" variant="outline" onClick={() => onCalibrateStart('leader')} disabled={busy}>
              校准主臂
            </Button>
          </div>
        ) : (
          <div className="space-y-2">
            <p className="text-muted-foreground">
              {calibrateTarget === 'leader'
                ? '主臂：移到零点姿态，看下方日志后点「继续」。'
                : '从臂：移到零点（夹爪闭合），看下方日志后点「继续」。'}
            </p>
            <div className="flex gap-2">
              <Button size="sm" onClick={onCalibrateContinue} disabled={busy}>
                继续
              </Button>
              <Button size="sm" variant="destructive" onClick={onCalibrateStop} disabled={busy}>
                取消
              </Button>
            </div>
          </div>
        )}
        {calibrateLog.length > 0 && (
          <pre className="max-h-24 overflow-auto rounded bg-black/40 p-2 text-[10px] text-muted-foreground">
            {calibrateLog.slice(-6).join('\n')}
          </pre>
        )}
      </div>
    </div>
  )
}
