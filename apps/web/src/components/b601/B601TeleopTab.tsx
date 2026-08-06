import { Loader2, Play, ScanLine, Square } from 'lucide-react'
import { Button } from '../ui/button'
import { B601AlignmentPanel } from './B601AlignmentPanel'
import type { B601Alignment } from '../../lib/b601Api'

interface Props {
  teleopRunning: boolean
  teleopStarting?: boolean
  teleopHealthy?: boolean
  recordRunning: boolean
  busy: boolean
  stopping?: boolean
  browseMode?: boolean
  needsCalibration?: boolean
  activeRobotId?: string | null
  activeLeaderId?: string | null
  useCameras?: boolean
  cameraLabel?: string
  onUseCamerasChange?: (v: boolean) => void
  alignment?: B601Alignment | null
  checkingAlignment?: boolean
  alignmentHint?: string | null
  onCheckAlignment?: () => void
  onForceStart?: () => void
  onStartTeleop: () => void
  onStopTeleop: () => void
  onRestartTeleop?: () => void
  logTail?: string[]
}

export function B601TeleopTab({
  teleopRunning,
  teleopStarting = false,
  teleopHealthy = true,
  recordRunning,
  busy,
  stopping = false,
  browseMode = false,
  needsCalibration = false,
  activeRobotId,
  activeLeaderId,
  useCameras = false,
  cameraLabel,
  onUseCamerasChange,
  alignment = null,
  checkingAlignment = false,
  alignmentHint = null,
  onCheckAlignment,
  onForceStart,
  onStartTeleop,
  onStopTeleop,
  onRestartTeleop,
  logTail = [],
}: Props) {
  return (
    <div className="space-y-4">
      {needsCalibration && !teleopRunning && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-amber-100">
          硬件已识别，但主从臂标定尚未完成。请回到「连接检查」步骤，在标定 ID 面板完成标定后再遥操。
        </div>
      )}

      {browseMode && !teleopRunning && (
        <div className="rounded-md border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-xs leading-relaxed text-sky-100">
          当前未检测到从臂或主臂。可先拖滑条熟悉 3D；接好线后在连接面板扫描即可。
        </div>
      )}

      {activeRobotId && !teleopRunning && (
        <div className="rounded-md border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-xs leading-relaxed text-violet-100">
          遥操将使用标定：
          <span className="font-mono font-medium">从臂 {activeRobotId}</span>
          {activeLeaderId ? (
            <>
              {' · '}
              <span className="font-mono font-medium">主臂 {activeLeaderId}</span>
            </>
          ) : null}
          。若与下拉框不一致或错用 follower1，从臂会猛窜 — 请确认下拉框 ID 正确后再启动。
        </div>
      )}

      <p className="text-xs leading-relaxed text-muted-foreground">
        <strong className="text-foreground/80">一键遥操：</strong>
        点「开始遥操」即可（自动唤醒 + 启动）。有关节掉线也会启动，掉线的关节不会动；卡住再点一次重连。
      </p>

      {onUseCamerasChange && (
        <label className="flex items-start gap-2 rounded-md border border-white/10 bg-black/20 px-3 py-2 text-xs">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={useCameras}
            disabled={teleopRunning || busy}
            onChange={(e) => onUseCamerasChange(e.target.checked)}
          />
          <span>
            带相机画面启动（官方 display_data）
            {cameraLabel ? (
              <span className="mt-0.5 block text-[10px] text-muted-foreground">使用 {cameraLabel}</span>
            ) : null}
          </span>
        </label>
      )}

      <B601AlignmentPanel
        alignment={alignment}
        checking={checkingAlignment}
        checkingHint={alignmentHint}
        onRecheck={onCheckAlignment}
        onForceStart={onForceStart}
        forceBusy={busy}
      />

      <div className="flex flex-wrap gap-2">
        {!teleopRunning ? (
          <>
            {onCheckAlignment && (
              <Button type="button" size="sm" variant="outline" disabled={busy || recordRunning} onClick={onCheckAlignment}>
                {checkingAlignment ? (
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                ) : (
                  <ScanLine className="mr-1 h-4 w-4" />
                )}
                检查对齐
              </Button>
            )}
            <Button size="sm" onClick={onStartTeleop} disabled={recordRunning}>
              {busy || teleopStarting ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Play className="mr-1 h-4 w-4" />
              )}
              {teleopStarting ? '重新连接' : '开始遥操'}
            </Button>
          </>
        ) : (
          <>
            <Button size="sm" variant="destructive" onClick={onStopTeleop} disabled={stopping}>
              {stopping ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Square className="mr-1 h-4 w-4 fill-current" />
              )}
              {stopping ? '卸力中…' : '停止遥操'}
            </Button>
            {onRestartTeleop && (
              <Button size="sm" variant="outline" onClick={onRestartTeleop} disabled={stopping}>
                重新启动
              </Button>
            )}
          </>
        )}
      </div>

      {stopping && (
        <p className="text-xs text-amber-200/90">
          正在卸力（先切断电机力矩，再停遥操进程）。若仍有电机声或臂在动，请立即拔 48V / 按急停。
        </p>
      )}

      {teleopRunning && !stopping && teleopHealthy && (
        <p className="text-xs text-emerald-400">遥操运行中 — 请缓慢移动主臂，观察从臂是否跟随</p>
      )}

      {teleopRunning && !stopping && !teleopHealthy && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          进程在跑但从臂可能未上力矩。请点「停止遥操」→「重新启动」，或回到连接步骤重新扫描从臂。
        </div>
      )}

      <p className="text-[10px] text-muted-foreground leading-relaxed">
        停止后会走官方 disconnect + 关节卸力，从臂应可手推。
        5 kg 为额定载荷；过载后需唤醒从臂再遥操。
      </p>

      {logTail.length > 0 && (
        <pre className="max-h-32 overflow-auto rounded bg-black/40 p-2 text-[10px] text-muted-foreground">
          {logTail.slice(-8).join('\n')}
        </pre>
      )}
    </div>
  )
}
