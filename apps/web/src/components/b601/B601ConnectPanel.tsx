import { useCallback, useState } from 'react'
import { ChevronDown, ChevronUp, Copy, Loader2, Plug } from 'lucide-react'
import { Button } from '../ui/button'
import { b601Probe, isB601HardwareReady, type B601Health } from '../../lib/b601Api'
import { B601MotorIdGrid } from './B601MotorIdGrid'

/** One-shot terminal fallback when user refuses to type password in the page. */
export const B601_CAN_TERMINAL_CMD = `sudo modprobe peak_usb 2>/dev/null
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000 restart-ms 100
sudo ip link set can0 up`

interface Props {
  health: B601Health | null
  onHealth: (h: B601Health) => void
  onActivity?: (kind: string) => void
  compact?: boolean
}

export function B601ConnectPanel({ health, onHealth, onActivity, compact }: Props) {
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [showTerminal, setShowTerminal] = useState(false)
  const [copied, setCopied] = useState(false)

  const needsConnect = !isB601HardwareReady(health)
  const isDm = health?.arm_variant === 'dm'
  const needsCan = health?.can_present && !health?.can_up
  const needsMotors = health?.can_up && (health?.motors_online ?? 0) < 4

  const connect = useCallback(async () => {
    setErr(null)
    setBusy(true)
    onActivity?.('health_poll')
    try {
      let h = await b601Probe({
        wakeFollower: false,
        sudoPassword: password.trim() || undefined,
      })
      if (h.can_up && (h.motors_online ?? 0) < 4) {
        onActivity?.('recover')
        h = await b601Probe({
          wakeFollower: true,
          sudoPassword: password.trim() || undefined,
        })
      }
      onHealth(h)
      if (!isB601HardwareReady(h)) {
        setErr(h.issues.join(' · ') || '仍未连上从臂，请检查 48V 电源和 CAN 线')
      } else {
        setPassword('')
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : '连接失败')
    } finally {
      setBusy(false)
    }
  }, [password, onHealth, onActivity])

  const copyCmd = async () => {
    try {
      await navigator.clipboard.writeText(B601_CAN_TERMINAL_CMD)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setErr('复制失败，请手动选中下方命令')
    }
  }

  if (!needsConnect) return null

  return (
    <div className="space-y-3 rounded-lg border border-amber-500/35 bg-amber-500/8 p-3">
      <div className="flex items-start gap-2">
        <Plug className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium text-amber-100">
            {isDm
              ? needsMotors
                ? '扫描 B601-DM 达妙电机'
                : '连接 B601-DM'
              : needsCan
                ? '连接从臂（需要一次本机密码）'
                : needsMotors
                  ? '唤醒从臂电机'
                  : '连接硬件'}
          </p>
          {!compact && (
            <p className="text-xs leading-relaxed text-amber-200/80">
              {isDm ? (
                <>
                  B601-DM 使用 USB-CAN 串口桥（当前 {health?.follower_port || '/dev/ttyACM2'}），不需要 sudo
                  打开 can0。点下面按钮会只读扫描 1~7 号达妙电机。
                </>
              ) : (
                <>
                  PCAN 插上了，但 CAN 还没打开。输入你<strong className="font-normal">这台 Linux 电脑的登录密码</strong>
                  （就是终端里 sudo 要的那个），点连接 — 密码只发给本机 Agent，不会上传云端，也不会保存。
                </>
              )}
            </p>
          )}
        </div>
      </div>

      {needsCan && !isDm && (
        <label className="block space-y-1">
          <span className="text-xs text-amber-200/70">本机 sudo 密码</span>
          <input
            type="password"
            autoComplete="current-password"
            className="w-full rounded-md border border-amber-500/30 bg-black/30 px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
            placeholder="输入电脑登录密码"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !busy) void connect()
            }}
          />
        </label>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => void connect()} disabled={busy || (needsCan && !isDm && !password.trim())}>
          {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
          {isDm ? '扫描 DM 从臂' : needsCan ? '连接 CAN 并扫描从臂' : '重新扫描从臂'}
        </Button>
        {!isDm && (
          <button
            type="button"
            className="inline-flex items-center gap-1 text-xs text-amber-200/70 hover:text-amber-100"
            onClick={() => setShowTerminal((v) => !v)}
          >
            {showTerminal ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            不想在网页输入？用终端
          </button>
        )}
      </div>

      {err && <p className="text-sm text-red-300">{err}</p>}

      {health?.motors && health.motors.length > 0 && (
        <B601MotorIdGrid motors={health.motors} compact={compact} />
      )}

      {health?.motors_scan_stale && (
        <p className="text-[10px] text-muted-foreground">电机状态为上次扫描（遥操占用 CAN 时不会重新 ping）</p>
      )}

      {showTerminal && !isDm && (
        <div className="space-y-2 rounded-md border border-white/10 bg-black/30 p-2">
          <p className="text-xs text-muted-foreground">
            复制下面整段，粘贴到本机终端，回车并输入密码。跑完再点上面的「连接 CAN 并扫描从臂」。
          </p>
          <pre className="overflow-x-auto rounded bg-black/50 p-2 text-[11px] leading-relaxed text-emerald-200/90">
            {B601_CAN_TERMINAL_CMD}
          </pre>
          <Button type="button" size="sm" variant="outline" onClick={() => void copyCmd()}>
            <Copy className="mr-1 h-3.5 w-3.5" />
            {copied ? '已复制' : '一键复制命令'}
          </Button>
        </div>
      )}
    </div>
  )
}
