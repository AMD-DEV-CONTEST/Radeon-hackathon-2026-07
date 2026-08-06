/**
 * SO-101 zero-install path: WebSerial → scan STS3215 → first-move ceremony.
 * Chrome / Edge only. Local Agent not required.
 *
 * 第一动作仪式（docs/strategy/2026-08-06-first-move-experience.md · U1）：
 *   ① 授权串口 → ② 舵机扫描点亮 → ③ 点「挥手」，真机 2 秒内动起来，🎉 庆祝 + 首录 CTA。
 * 安全纪律：断开关扭矩、写位置钳制 0..4095、扫描空档给可执行排查指引（不给红色报错码）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Cable,
  Check,
  ChevronDown,
  Loader2,
  PartyPopper,
  Power,
  Unplug,
  Waves,
} from 'lucide-react'
import { Button } from '../ui/button'
import { UrdfViewer } from '../features/UrdfViewer'
import { SerialDiagnostics } from './SerialDiagnostics'
import { isWebSerialSupported, StsSerialBus } from '../../lib/webserial'

/**
 * STS3215 计数 → 弧度（0.088°/count ≈ 360°/4096）。
 * SO-101 URDF 的关节名就是电机 ID（"1".."6"），映射天然对齐。
 * 注意：孪生是视觉跟动（零点/方向以真机标定为准），不是标定级控制。
 */
const COUNT_TO_RAD = (0.088 * Math.PI) / 180

const JOINT_LABELS = [
  { id: 1, name: 'shoulder_pan' },
  { id: 2, name: 'shoulder_lift' },
  { id: 3, name: 'elbow_flex' },
  { id: 4, name: 'wrist_flex' },
  { id: 5, name: 'wrist_roll' },
  { id: 6, name: 'gripper' },
] as const

type JointState = {
  id: number
  name: string
  present: number
  goal: number
  online: boolean
}

/** 挥手姿态（相对基准位置的增量，≈±11°，安全低速） */
const WAVE_UP: Record<string, number> = {
  shoulder_pan: 0,
  shoulder_lift: 260,
  elbow_flex: -140,
  wrist_flex: 0,
  wrist_roll: -300,
  gripper: 500,
}
const WAVE_DOWN: Record<string, number> = {
  shoulder_pan: 0,
  shoulder_lift: -260,
  elbow_flex: 140,
  wrist_flex: 0,
  wrist_roll: 300,
  gripper: -300,
}
const WAVE_STEP_MS = 350
const WAVE_CYCLES = 2

interface SavedDataset {
  dataset_id: string
  name: string
  frame_count: number
}

export function BrowserDirectPanel() {
  const busRef = useRef<StsSerialBus | null>(null)
  const [supported] = useState(() => isWebSerialSupported())
  const [busy, setBusy] = useState<string | null>(null)
  const [showDiag, setShowDiag] = useState(false)
  const [connected, setConnected] = useState(false)
  const [torqueOn, setTorqueOn] = useState(false)
  const [celebrated, setCelebrated] = useState(false)
  const [recording, setRecording] = useState(false)
  const [lastDataset, setLastDataset] = useState<SavedDataset | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const framesRef = useRef<Array<{ timestamp: number; joints: Record<string, number> }>>([])
  const [joints, setJoints] = useState<JointState[]>(
    JOINT_LABELS.map((j) => ({
      id: j.id,
      name: j.name,
      present: 2048,
      goal: 2048,
      online: false,
    })),
  )

  useEffect(() => {
    return () => {
      void busRef.current?.close()
      busRef.current = null
    }
  }, [])

  const onlineCount = joints.filter((j) => j.online).length

  /** 3D 孪生关节值：goal 实时驱动（滑条 / 挥手序列都会让它跟动） */
  const twinJoints = useMemo(() => {
    const out: Record<string, number> = {}
    for (const j of joints) out[String(j.id)] = (j.goal - 2048) * COUNT_TO_RAD
    return out
  }, [joints])
  const steps = [
    { label: '授权串口', done: connected },
    { label: '扫描舵机', done: onlineCount > 0 },
    { label: '第一次挥手', done: celebrated },
  ]

  const connect = useCallback(async () => {
    setBusy('connect')
    setError(null)
    setNotice(null)
    try {
      const bus = new StsSerialBus()
      await bus.requestAndOpen()
      busRef.current = bus
      setConnected(true)
      setNotice('串口已授权。正在扫描舵机 ID 1–6…')
      const found = await bus.scan()
      if (found.length === 0) {
        setError('no-servo')
        setJoints((prev) => prev.map((j) => ({ ...j, online: false })))
        return
      }
      const next: JointState[] = []
      for (const meta of JOINT_LABELS) {
        const online = found.includes(meta.id)
        let present = 2048
        if (online) {
          try {
            present = await bus.readPosition(meta.id)
          } catch {
            present = 2048
          }
        }
        next.push({
          id: meta.id,
          name: meta.name,
          present,
          goal: present,
          online,
        })
      }
      setJoints(next)
      setNotice(`扫到 ${found.length} 个舵机：${found.join(', ')}。点「挥手」，让它动一下。`)
    } catch (e) {
      setConnected(false)
      busRef.current = null
      const msg = e instanceof Error ? e.message : String(e)
      if (/NotFoundError|No port selected/i.test(msg)) {
        setError('已取消串口选择。')
      } else {
        setError(msg)
      }
    } finally {
      setBusy(null)
    }
  }, [])

  const disconnect = useCallback(async () => {
    setBusy('disconnect')
    try {
      if (busRef.current && torqueOn) {
        for (const j of joints.filter((x) => x.online)) {
          try {
            await busRef.current.setTorque(j.id, false)
          } catch {
            /* ignore */
          }
        }
      }
      await busRef.current?.close()
    } finally {
      busRef.current = null
      setConnected(false)
      setTorqueOn(false)
      setCelebrated(false)
      setLastDataset(null)
      setJoints(JOINT_LABELS.map((j) => ({ id: j.id, name: j.name, present: 2048, goal: 2048, online: false })))
      setBusy(null)
      setNotice('已断开。')
    }
  }, [joints, torqueOn])

  const toggleTorque = useCallback(async () => {
    const bus = busRef.current
    if (!bus) return
    setBusy('torque')
    setError(null)
    try {
      const enable = !torqueOn
      for (const j of joints.filter((x) => x.online)) {
        await bus.setTorque(j.id, enable)
        await new Promise((r) => setTimeout(r, 6))
      }
      setTorqueOn(enable)
      setNotice(enable ? '扭矩已开。慢一点拖滑条。' : '扭矩已关，可以手推关节。')
    } catch (e) {
      setError(e instanceof Error ? e.message : '扭矩切换失败')
    } finally {
      setBusy(null)
    }
  }, [joints, torqueOn])

  /** 仪式核心：自动开扭矩 → 2 轮安全挥手 → 回到基准 → 🎉（每姿态一条广播包，半双工友好） */
  const runWave = useCallback(async () => {
    const bus = busRef.current
    if (!bus || !connected) return
    setBusy('wave')
    setError(null)
    setNotice('开始挥手…第一次动作马上就来')
    try {
      const online = joints.filter((j) => j.online)
      for (const j of online) await bus.setTorque(j.id, true)
      setTorqueOn(true)
      await new Promise((r) => setTimeout(r, 150)) // 等扭矩生效
      const pose = async (deltas: Record<string, number>) => {
        const entries = online.map((j) => ({
          id: j.id,
          value: j.present + (deltas[j.name] ?? 0),
        }))
        await bus.writePositionsMany(entries)
        setJoints((prev) =>
          prev.map((p) => {
            const e = entries.find((x) => x.id === p.id)
            return e ? { ...p, goal: e.value } : p
          }),
        )
        await new Promise((r) => setTimeout(r, WAVE_STEP_MS))
      }
      for (let cycle = 0; cycle < WAVE_CYCLES; cycle++) {
        await pose(WAVE_UP)
        await pose(WAVE_DOWN)
      }
      await bus.writePositionsMany(online.map((j) => ({ id: j.id, value: j.present })))
      setJoints((prev) => prev.map((p) => ({ ...p, goal: p.present })))
      setCelebrated(true)
      setNotice('第一次动起来了！')
    } catch (e) {
      setError(e instanceof Error ? e.message : '挥手失败')
    } finally {
      setBusy(null)
    }
  }, [connected, joints])

  /**
   * U3 首录：**重放挥手序列期间采样**（存的是真的「第一次挥手」动作，
   * 而非静止姿态——M43 审计 H1 修复）。每姿态广播写后读一帧 present。
   */
  const startRecord = useCallback(async () => {
    const bus = busRef.current
    if (!bus || !connected) return
    setBusy('record')
    setRecording(true)
    setError(null)
    framesRef.current = []
    const online = joints.filter((j) => j.online)
    try {
      for (const j of online) await bus.setTorque(j.id, true)
      setTorqueOn(true)
      await new Promise((r) => setTimeout(r, 150))
      const t0 = performance.now()
      const sample = async () => {
        const frame = { timestamp: (performance.now() - t0) / 1000, joints: {} as Record<string, number> }
        for (const j of online) {
          try {
            frame.joints[String(j.id)] = await bus.readPosition(j.id)
          } catch {
            /* 单关节读失败跳过，不中断录制 */
          }
        }
        framesRef.current.push(frame)
      }
      const pose = async (deltas: Record<string, number>) => {
        const entries = online.map((j) => ({ id: j.id, value: j.present + (deltas[j.name] ?? 0) }))
        await bus.writePositionsMany(entries)
        setJoints((prev) =>
          prev.map((p) => {
            const e = entries.find((x) => x.id === p.id)
            return e ? { ...p, goal: e.value } : p
          }),
        )
        await new Promise((r) => setTimeout(r, 120))
        await sample()
        await new Promise((r) => setTimeout(r, WAVE_STEP_MS - 120))
      }
      for (let cycle = 0; cycle < WAVE_CYCLES; cycle++) {
        await pose(WAVE_UP)
        await pose(WAVE_DOWN)
      }
      await bus.writePositionsMany(online.map((j) => ({ id: j.id, value: j.present })))
      await new Promise((r) => setTimeout(r, 120))
      await sample()
      setJoints((prev) => prev.map((p) => ({ ...p, goal: p.present })))
    } finally {
      setRecording(false)
      setBusy(null)
    }
    if (framesRef.current.length < 3) {
      setError('录制帧太少，请重试。')
      return
    }
    setBusy('record')
    try {
      const res = await fetch('/api/datasets/record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: '我的第一条数据',
          robot_id: 'so101',
          fps: 20,
          frames: framesRef.current,
        }),
      })
      if (!res.ok) throw new Error(`保存失败 (${res.status})`)
      const saved = (await res.json()) as SavedDataset
      setLastDataset(saved)
      setNotice(`第一条数据已入库：${saved.name}（${saved.frame_count} 帧）`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败')
    } finally {
      setBusy(null)
    }
  }, [busy, connected, joints])

  const onSlide = useCallback(
    async (id: number, value: number) => {
      setJoints((prev) => prev.map((j) => (j.id === id ? { ...j, goal: value } : j)))
      const bus = busRef.current
      if (!bus || !torqueOn) return
      try {
        await bus.writePosition(id, value)
      } catch (e) {
        setError(e instanceof Error ? e.message : '写位置失败')
      }
    },
    [torqueOn],
  )

  if (!supported) {
    return (
      <div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-6 text-sm leading-relaxed text-amber-100/90">
        <p className="font-medium">浏览器直连需要 Chrome 或 Edge</p>
        <p className="mt-2 text-amber-100/70">
          Firefox / Safari 不支持 WebSerial。请换 Chromium 系浏览器，或改走{' '}
          <Link to="/robots/so101?mode=agent" className="underline underline-offset-2">
            Local Agent 向导
          </Link>
          。
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-sky-400/25 bg-sky-400/5 px-4 py-3 text-sm text-sky-100/90">
        手里还没有 SO-101？{' '}
        <Link
          to="/robots/reachy_mini?guide=virtual&play=1"
          className="font-medium text-[var(--paper)] underline underline-offset-2"
        >
          去玩云端虚拟 Reachy
        </Link>
        ——能看 3D、能点动作，零硬件。
      </div>

      <div className="rounded-2xl border border-white/10 bg-gradient-to-br from-[var(--ember)]/10 to-transparent p-5 sm:p-6">
        <p className="font-display text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--ember)]">
          Zero install · WebSerial
        </p>
        <h2 className="font-display mt-2 text-2xl font-bold tracking-tight">浏览器直连 SO-101</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-stone-400">
          插上 USB → 点授权 → 扫到舵机 → 点「挥手」。不装 Local Agent，不信任自签证书，不占终端窗口。
        </p>

        {/* 步骤指示 */}
        <div className="mt-4 flex flex-wrap gap-2">
          {steps.map((s) => (
            <span
              key={s.label}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs ${
                s.done
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
                  : 'border-white/10 text-stone-500'
              }`}
            >
              {s.done ? <Check className="h-3 w-3" /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
              {s.label}
            </span>
          ))}
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          {!connected ? (
            <Button onClick={() => void connect()} disabled={busy != null}>
              {busy === 'connect' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Cable className="h-4 w-4" />}
              授权串口并扫描
            </Button>
          ) : (
            <>
              <Button
                onClick={() => void runWave()}
                disabled={busy != null || onlineCount === 0}
                className="h-11 px-8 text-base"
              >
                {busy === 'wave' ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  <Waves className="h-5 w-5" />
                )}
                挥手
              </Button>
              <Button variant="outline" onClick={() => void disconnect()} disabled={busy != null}>
                <Unplug className="h-4 w-4" />
                断开
              </Button>
            </>
          )}
        </div>

        {/* 3D 孪生：连接后实时跟动（滑条 / 挥手都驱动它） */}
        <div className="mt-5 overflow-hidden rounded-2xl border border-white/10 bg-black/25">
          <div className="flex items-center justify-between border-b border-white/5 px-4 py-2">
            <span className="text-[11px] uppercase tracking-[0.18em] text-stone-500">
              3D 跟动 {connected ? '· 实时' : '· 待连接'}
            </span>
            {torqueOn && <span className="text-[11px] text-emerald-300/80">扭矩开</span>}
          </div>
          <div className="h-44">
            <UrdfViewer joints={twinJoints} hideMeshProgress />
          </div>
        </div>

        {celebrated && (
          <div className="mt-5 rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-5">
            <div className="flex items-center gap-3">
              <PartyPopper className="h-7 w-7 shrink-0 text-emerald-300" />
              <div>
                <p className="font-display text-lg font-bold">第一次动起来了</p>
                <p className="text-xs text-emerald-100/70">
                  你的 SO-101 完成了第一次挥手。真实关节数据从这里开始，可以进入采集 → 训练 → 部署的闭环。
                </p>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <Button onClick={() => void startRecord()} disabled={busy != null}>
                {recording ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                {recording ? '录制中（3 秒）…' : '把这段存成我的第一条数据'}
              </Button>
              {lastDataset && (
                <Link
                  to="/datasets"
                  className="text-xs text-emerald-200/80 underline underline-offset-2 hover:text-emerald-100"
                >
                  去实验室看 {lastDataset.name}（{lastDataset.frame_count} 帧）→
                </Link>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 提示 / 错误 */}
      {error === 'no-servo' ? (
        <div className="space-y-3">
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-xs leading-relaxed text-amber-100/90">
            <p className="font-medium">没扫到舵机，按顺序排查：</p>
            <ol className="mt-2 list-decimal space-y-1 pl-4">
              <li>确认 USB 已插紧（可以换一个 USB 口试试）</li>
              <li>确认电机供电：STS3215 需要独立电源，单靠 USB 供电不足</li>
              <li>关闭占用串口的程序（Local Agent、串口调试工具）</li>
              <li>换一根数据线——部分线只充电、不传数据</li>
            </ol>
          </div>
          {/* U4：浏览器内诊断（会先释放当前连接），日志可导出给支持团队 */}
          <SerialDiagnostics onRelease={disconnect} />
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs text-red-200">
          {error}
        </div>
      ) : notice ? (
        <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-4 py-3 text-xs text-emerald-100">
          {notice}
        </div>
      ) : null}

      {/* 断开状态下的一键诊断入口 */}
      {!connected && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => setShowDiag((v) => !v)}
            className="text-[11px] text-stone-500 underline-offset-2 hover:text-stone-300 hover:underline"
          >
            {showDiag ? '收起诊断' : '串口诊断 / 导出日志'}
          </button>
        </div>
      )}
      {showDiag && !connected && <SerialDiagnostics />}

      {/* 高级：手动关节（仪式之外再展开） */}
      <details className="group rounded-2xl border border-white/10 bg-black/20 p-4 sm:p-5">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
          <h3 className="text-sm font-medium">高级：手动关节与扭矩</h3>
          <ChevronDown className="h-4 w-4 text-stone-500 transition-transform group-open:rotate-180" />
        </summary>
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              onClick={() => void toggleTorque()}
              disabled={busy != null || onlineCount === 0}
              variant={torqueOn ? 'destructive' : 'default'}
            >
              {busy === 'torque' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Power className="h-4 w-4" />}
              {torqueOn ? '关闭扭矩' : '开启扭矩'}
            </Button>
            <span className="text-[11px] text-stone-500">
              {connected ? (torqueOn ? '扭矩开 · 可拖动' : '扭矩关 · 只读') : '未连接'}
            </span>
          </div>
          {joints.map((j) => (
            <label key={j.id} className={`block space-y-1.5 ${j.online ? '' : 'opacity-40'}`}>
              <div className="flex items-baseline justify-between text-xs">
                <span>
                  <span className="font-mono text-stone-300">#{j.id}</span>{' '}
                  <span className="text-stone-400">{j.name}</span>
                  {!j.online && <span className="ml-2 text-stone-600">离线</span>}
                </span>
                <span className="font-mono tabular-nums text-stone-500">{j.goal}</span>
              </div>
              <input
                type="range"
                min={0}
                max={4095}
                value={j.goal}
                disabled={!j.online || !connected || !torqueOn || busy != null}
                onChange={(e) => void onSlide(j.id, Number(e.target.value))}
                className="w-full accent-[var(--ember)]"
              />
            </label>
          ))}
          <p className="text-xs text-stone-500">
            需要录大数据集、主从遥操闭环或接其它机型时，再装{' '}
            <Link to="/robots/so101?mode=agent" className="text-stone-300 underline-offset-2 hover:underline">
              Local Agent 向导
            </Link>
            。
          </p>
        </div>
      </details>
    </div>
  )
}
