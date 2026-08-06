import { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { Button } from '../ui/button'
import {
  b601CalibrateContinue,
  b601CalibrateStart,
  b601CalibrateStop,
  deleteB601Calibration,
  getB601Config,
  setB601Config,
  type B601Config,
} from '../../lib/b601Api'

interface Props {
  hardwareReady: boolean
  calibrateRunning: boolean
  calibrateTarget?: string | null
  calibrateLog?: string[]
  busy: boolean
  onCalibrateChange?: () => void
}

function CalIdRow({
  label,
  side,
  pick,
  config,
  fileOk,
  ids,
  newId,
  onNewIdChange,
  disabled,
  onPickChange,
  onRecalibrate,
  onDelete,
  onStartNew,
  hardwareReady,
}: {
  label: string
  side: 'follower' | 'leader'
  pick: string
  config: B601Config
  fileOk: boolean
  ids: string[]
  newId: string
  onNewIdChange: (v: string) => void
  disabled: boolean
  hardwareReady: boolean
  onPickChange: (v: string) => void
  onRecalibrate: () => void
  onDelete: () => void
  onStartNew: () => void
}) {
  const activeId = side === 'follower' ? config.robot_id : config.leader_id
  const isNew = pick === '__new__'
  const canDelete = !isNew && ids.length > 0 && (ids.length > 1 || pick !== activeId)

  return (
    <div className="space-y-1.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <div className="flex flex-wrap items-center gap-1.5">
        <select
          className="min-w-[140px] flex-1 rounded-md border border-white/10 bg-black/40 px-2 py-1.5 text-xs"
          value={pick}
          disabled={disabled}
          onChange={(e) => onPickChange(e.target.value)}
        >
          {ids.map((id) => (
            <option key={id} value={id}>
              {id}
              {id === activeId ? ' · 使用中' : ''}
              {id === activeId && (fileOk ? ' ✓' : ' ✗')}
            </option>
          ))}
          {activeId && !ids.includes(activeId) && (
            <option value={activeId}>
              {activeId} · 使用中 ✗
            </option>
          )}
          <option value="__new__">+ 用新名称标定…</option>
        </select>
        {!isNew && (
          <>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-8 text-xs"
              disabled={disabled || !hardwareReady}
              title={`对当前选中的「${pick}」重新做零点标定，会覆盖同名文件`}
              onClick={onRecalibrate}
            >
              覆盖标定
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-8 px-2 text-red-300 hover:text-red-200"
              disabled={disabled || !canDelete}
              title={canDelete ? '删除此标定文件' : '至少保留一个标定，或先切换到别的 ID'}
              onClick={onDelete}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </>
        )}
      </div>
      {isNew && (
        <div className="flex flex-wrap items-center gap-1.5">
          <input
            className="min-w-[140px] flex-1 rounded-md border border-white/10 bg-black/40 px-2 py-1.5 text-xs"
            placeholder={side === 'follower' ? '例如 follower1' : '例如 rebot_arm_102_leader'}
            value={newId}
            onChange={(e) => onNewIdChange(e.target.value)}
          />
          <Button type="button" size="sm" disabled={disabled || !newId.trim()} onClick={onStartNew}>
            <Plus className="mr-1 h-3 w-3" />
            开始标定
          </Button>
        </div>
      )}
    </div>
  )
}

export function B601CalibrationPanel({
  hardwareReady,
  calibrateRunning,
  calibrateTarget,
  calibrateLog = [],
  busy,
  onCalibrateChange,
}: Props) {
  const [config, setConfig] = useState<B601Config | null>(null)
  const [loading, setLoading] = useState(false)
  const [newFollowerId, setNewFollowerId] = useState('')
  const [newLeaderId, setNewLeaderId] = useState('')
  const [followerPick, setFollowerPick] = useState('')
  const [leaderPick, setLeaderPick] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const wasCalibrating = useRef(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const c = await getB601Config()
      setConfig(c)
      setFollowerPick(c.robot_id)
      setLeaderPick(c.leader_id)
    } catch (e) {
      setErr(e instanceof Error ? e.message : '无法读取标定配置')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    if (calibrateRunning) {
      wasCalibrating.current = true
      return
    }
    if (!wasCalibrating.current) return
    wasCalibrating.current = false
    const saved = calibrateLog.some(
      (line) => /calibration saved/i.test(line) || /Arm zero position set/i.test(line),
    )
    void refresh().then(() => {
      if (saved) {
        setSuccess('标定已保存')
        setErr(null)
      }
    })
  }, [calibrateRunning, calibrateLog, refresh])

  const applySelection = async (side: 'follower' | 'leader', id: string) => {
    setErr(null)
    setSuccess(null)
    try {
      const c = await setB601Config(
        side === 'follower' ? { robot_id: id } : { leader_id: id },
      )
      setConfig(c)
      if (side === 'follower') setFollowerPick(c.robot_id)
      else setLeaderPick(c.leader_id)
      setSuccess(`已切换到 ${id}`)
      onCalibrateChange?.()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '切换标定失败')
      void refresh()
    }
  }

  const startCalibrate = async (target: 'follower' | 'leader', idOverride?: string) => {
    setErr(null)
    setSuccess(null)
    try {
      if (target === 'follower' && idOverride) await setB601Config({ robot_id: idOverride })
      if (target === 'leader' && idOverride) await setB601Config({ leader_id: idOverride })
      setSuccess(`已切换到 ${idOverride ?? (target === 'follower' ? config?.robot_id : config?.leader_id) ?? ''}`)
      await b601CalibrateStart(target, {
        robotId: target === 'follower' ? idOverride : undefined,
        leaderId: target === 'leader' ? idOverride : undefined,
      })
      onCalibrateChange?.()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '启动标定失败')
    }
  }

  const removeCal = async (side: 'follower' | 'leader', calId: string) => {
    if (!window.confirm(`删除标定「${calId}」？`)) return
    setErr(null)
    setSuccess(null)
    try {
      const c = await deleteB601Calibration(side, calId)
      setConfig(c)
      setFollowerPick(c.robot_id)
      setLeaderPick(c.leader_id)
      onCalibrateChange?.()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '删除失败')
    }
  }

  if (!config && loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
        <Loader2 className="h-4 w-4 animate-spin" />
        加载标定…
      </div>
    )
  }

  if (!config) return null

  return (
    <div className="space-y-3 border-t border-white/5 pt-3">
      <p className="text-xs text-muted-foreground leading-relaxed">
        每个下拉项是一套标定文件（例如 follower1、follower2）。
        <strong className="font-normal text-foreground/80">覆盖标定</strong>
        = 仍用当前名字，重新标一次并覆盖原文件；
        <strong className="font-normal text-foreground/80">用新名称标定</strong>
        = 另存为新名字（适合第二台从臂或备份）。
      </p>

      <div className="grid gap-3 sm:grid-cols-2">
        <CalIdRow
          label="从臂标定 ID"
          side="follower"
          pick={followerPick}
          config={config}
          fileOk={config.calibration_follower}
          ids={config.follower_ids}
          newId={newFollowerId}
          onNewIdChange={setNewFollowerId}
          disabled={calibrateRunning || busy}
          hardwareReady={hardwareReady}
          onPickChange={(v) => {
            if (v === '__new__') {
              setFollowerPick(v)
              return
            }
            void applySelection('follower', v)
          }}
          onRecalibrate={() => void startCalibrate('follower')}
          onDelete={() => void removeCal('follower', followerPick)}
          onStartNew={() => void startCalibrate('follower', newFollowerId.trim())}
        />
        <CalIdRow
          label="主臂标定 ID"
          side="leader"
          pick={leaderPick}
          config={config}
          fileOk={config.calibration_leader}
          ids={config.leader_ids}
          newId={newLeaderId}
          onNewIdChange={setNewLeaderId}
          disabled={calibrateRunning || busy}
          hardwareReady={hardwareReady}
          onPickChange={(v) => {
            if (v === '__new__') {
              setLeaderPick(v)
              return
            }
            void applySelection('leader', v)
          }}
          onRecalibrate={() => void startCalibrate('leader')}
          onDelete={() => void removeCal('leader', leaderPick)}
          onStartNew={() => void startCalibrate('leader', newLeaderId.trim())}
        />
      </div>

      {success && (
        <p className="text-xs text-emerald-400">{success}</p>
      )}

      {calibrateRunning && (
        <div className="space-y-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-2">
          <p className="text-[11px] text-amber-100">
            {calibrateTarget === 'leader'
              ? '主臂移到零点并保持不动，然后点继续。'
              : '从臂移到零点（夹爪闭合），然后点继续。'}
          </p>
          <div className="flex gap-2">
            <Button size="sm" disabled={busy} onClick={() => void b601CalibrateContinue().then(() => onCalibrateChange?.())}>
              继续
            </Button>
            <Button size="sm" variant="destructive" disabled={busy} onClick={() => void b601CalibrateStop().then(() => refresh()).then(() => onCalibrateChange?.())}>
              取消
            </Button>
          </div>
          {calibrateLog.length > 0 && (
            <pre className="max-h-24 overflow-auto rounded bg-black/40 p-2 text-[10px] text-muted-foreground">
              {calibrateLog.slice(-6).join('\n')}
            </pre>
          )}
        </div>
      )}

      {err && <p className="text-xs text-destructive">{err}</p>}
    </div>
  )
}
