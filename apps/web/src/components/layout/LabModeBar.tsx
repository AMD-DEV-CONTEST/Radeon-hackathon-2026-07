import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, FlaskConical, Loader2, Settings2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { agentFetch } from '../../lib/localAgent'
import { authJson } from '../../lib/auth'
import { useAuth } from '../../lib/authContext'
import { cn } from '../../lib/utils'

const LAB_MODE_KEY = 'botversex_lab_mode'
const LAB_SEAT_URLS_KEY = 'botversex_lab_seat_urls'

interface LabSeat {
  seat_id: string
  label: string
  role: string
}

interface SeatHealth {
  ok: boolean | null
  detail?: string
}

function loadSeatUrls(): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(LAB_SEAT_URLS_KEY)
    return raw ? (JSON.parse(raw) as Record<string, string>) : {}
  } catch {
    return {}
  }
}

async function probeAgentBase(baseUrl: string): Promise<{ ok: boolean; detail: string }> {
  const url = `${baseUrl.replace(/\/$/, '')}/api/setup/health`
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(4000) })
    if (!r.ok) return { ok: false, detail: `HTTP ${r.status}` }
    return { ok: true, detail: 'Agent 在线' }
  } catch (e) {
    return { ok: false, detail: e instanceof Error ? e.message : '无法连接' }
  }
}

export function useLabModeEnabled() {
  const [enabled, setEnabled] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem(LAB_MODE_KEY) === '1'
  })

  const toggle = useCallback(() => {
    setEnabled((prev) => {
      const next = !prev
      window.localStorage.setItem(LAB_MODE_KEY, next ? '1' : '0')
      return next
    })
  }, [])

  return { enabled, toggle }
}

export function LabModeBar() {
  const { token } = useAuth()
  const { enabled, toggle } = useLabModeEnabled()
  const [open, setOpen] = useState(false)
  const [seats, setSeats] = useState<LabSeat[]>([])
  const [health, setHealth] = useState<Record<string, SeatHealth>>({})
  const [probing, setProbing] = useState(false)
  const [seatUrls, setSeatUrls] = useState<Record<string, string>>(() =>
    typeof window !== 'undefined' ? loadSeatUrls() : {},
  )

  useEffect(() => {
    if (!enabled || !token) return
    void authJson<{ seats: LabSeat[] }>('/api/v1/agents/lab/seats')
      .then((r) => setSeats(r.seats ?? []))
      .catch(() => setSeats([]))
  }, [enabled, token])

  const displaySeats =
    seats.length > 0
      ? seats
      : [
          { seat_id: 'seat-1', label: '工位 1（本机）', role: 'primary' },
          { seat_id: 'seat-2', label: '工位 2', role: 'member' },
          { seat_id: 'seat-3', label: '工位 3', role: 'member' },
          { seat_id: 'seat-4', label: '工位 4', role: 'member' },
          { seat_id: 'seat-5', label: '工位 5', role: 'member' },
        ]

  const runProbe = useCallback(async () => {
    setProbing(true)
    const next: Record<string, SeatHealth> = {}
    for (const seat of displaySeats) {
      if (seat.seat_id === 'seat-1' || seat.role === 'primary') {
        try {
          const r = await agentFetch('/api/setup/health', { timeoutMs: 4000 })
          next[seat.seat_id] = {
            ok: r.ok,
            detail: r.ok ? '本机 Agent 已连接' : '本机 Agent 未响应',
          }
        } catch {
          next[seat.seat_id] = { ok: false, detail: '本机 Agent 未启动 — 去 Setup 安装' }
        }
        continue
      }
      const url = seatUrls[seat.seat_id]
      if (!url) {
        next[seat.seat_id] = { ok: null, detail: '未配置 Agent 地址' }
        continue
      }
      const result = await probeAgentBase(url)
      next[seat.seat_id] = { ok: result.ok, detail: result.detail }
    }
    setHealth(next)
    setProbing(false)
  }, [displaySeats, seatUrls])

  useEffect(() => {
    if (!enabled) return
    void runProbe()
    const t = window.setInterval(() => void runProbe(), 15_000)
    return () => window.clearInterval(t)
  }, [enabled, runProbe])

  const configureSeat = (seatId: string) => {
    const current = seatUrls[seatId] ?? ''
    const input = window.prompt(
      `${seatId} 的 Local Agent 地址（例：https://192.168.1.12:8002）\n留空则清除`,
      current,
    )
    if (input === null) return
    const trimmed = input.trim()
    const updated = { ...seatUrls }
    if (trimmed) updated[seatId] = trimmed
    else delete updated[seatId]
    setSeatUrls(updated)
    window.localStorage.setItem(LAB_SEAT_URLS_KEY, JSON.stringify(updated))
    void runProbe()
  }

  if (!enabled) {
    return (
      <button
        type="button"
        onClick={toggle}
        className="hidden lg:inline-flex items-center gap-1 rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[10px] text-muted-foreground hover:bg-[hsl(var(--muted))]"
        title="实验室模式：查看多台机器的 Local Agent 是否在线（Pro 5 席位 pack）"
      >
        <FlaskConical className="h-3 w-3" />
        实验室
      </button>
    )
  }

  return (
    <div className="relative hidden lg:block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--primary))]/25 bg-[hsl(var(--primary))]/5 px-2.5 py-1 text-[10px] font-medium text-[hsl(var(--primary))]"
      >
        <FlaskConical className="h-3 w-3" />
        实验室
        <div className="flex items-center gap-0.5">
          {displaySeats.map((seat) => {
            const h = health[seat.seat_id]
            return (
              <span
                key={seat.seat_id}
                className={cn(
                  'h-1.5 w-1.5 rounded-full',
                  h?.ok === true && 'bg-emerald-400',
                  h?.ok === false && 'bg-red-400',
                  h?.ok == null && 'bg-muted-foreground/40',
                )}
              />
            )
          })}
        </div>
        <ChevronDown className={cn('h-3 w-3 transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-40 cursor-default"
            aria-label="关闭"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 top-full z-50 mt-2 w-72 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--popover))] p-3 shadow-xl text-xs">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="font-semibold text-[hsl(var(--foreground))]">实验室工位</p>
              <button
                type="button"
                onClick={toggle}
                className="text-[10px] text-muted-foreground hover:text-foreground"
              >
                关闭模式
              </button>
            </div>
            <p className="mb-3 leading-relaxed text-muted-foreground">
              给 PI / 管理员一眼看：哪台电脑的 Local Agent 在线。工位 1 是本机；其余填局域网地址（如
              <code className="mx-0.5 text-[10px]">https://192.168.x.x:8002</code>）。
            </p>

            <ul className="space-y-2">
              {displaySeats.map((seat) => {
                const h = health[seat.seat_id]
                const isPrimary = seat.seat_id === 'seat-1' || seat.role === 'primary'
                return (
                  <li
                    key={seat.seat_id}
                    className="flex items-start gap-2 rounded-lg border border-[hsl(var(--border))]/60 px-2 py-1.5"
                  >
                    <span
                      className={cn(
                        'mt-1 h-2 w-2 shrink-0 rounded-full',
                        h?.ok === true && 'bg-emerald-400',
                        h?.ok === false && 'bg-red-400',
                        h?.ok == null && 'bg-muted-foreground/40',
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="font-medium">{seat.label}</div>
                      <div className="text-[10px] text-muted-foreground truncate">
                        {h?.detail ?? (probing ? '检测中…' : '—')}
                      </div>
                    </div>
                    {!isPrimary && (
                      <button
                        type="button"
                        title="配置 Agent URL"
                        className="shrink-0 p-0.5 text-muted-foreground hover:text-foreground"
                        onClick={() => configureSeat(seat.seat_id)}
                      >
                        <Settings2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>

            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={probing}
                onClick={() => void runProbe()}
                className="inline-flex items-center gap-1 rounded-md border border-[hsl(var(--border))] px-2 py-1 text-[10px] hover:bg-[hsl(var(--muted))]"
              >
                {probing ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                重新检测
              </button>
              <Link
                to="/setup"
                onClick={() => setOpen(false)}
                className="rounded-md bg-[hsl(var(--primary))] px-2 py-1 text-[10px] text-[hsl(var(--primary-foreground))]"
              >
                本机 Setup
              </Link>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
