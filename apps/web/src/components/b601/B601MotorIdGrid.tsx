import type { B601MotorScanItem } from '../../lib/b601Api'

const FALLBACK_LABELS: Record<number, string> = {
  1: '底座',
  2: '大臂',
  3: '小臂',
  4: '腕1',
  5: '腕2',
  6: '腕3',
  7: '夹爪',
}

interface Props {
  motors?: B601MotorScanItem[]
  compact?: boolean
}

export function B601MotorIdGrid({ motors, compact }: Props) {
  if (!motors?.length) return null

  return (
    <div className="space-y-1.5">
      <p className="text-[10px] text-muted-foreground">
        逐 ID 检测（只读 ping，不写寄存器）— 对齐 Seeed 成品套件 1~7 扫描
      </p>
      <div className={`grid gap-1 ${compact ? 'grid-cols-7' : 'grid-cols-2 sm:grid-cols-4'}`}>
        {motors.map((m) => {
          const name = m.label?.replace(/^ID\d+\s*/, '') || FALLBACK_LABELS[m.motor_id] || `ID${m.motor_id}`
          return (
            <div
              key={m.motor_id}
              className={`rounded border px-2 py-1 text-[10px] ${
                m.online
                  ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-100'
                  : 'border-red-500/40 bg-red-500/10 text-red-100'
              }`}
              title={m.model}
            >
              <span className="font-mono font-medium">ID{m.motor_id}</span>
              {!compact && <span className="ml-1 opacity-80">{name}</span>}
              <span className="float-right">{m.online ? '✓' : '✗'}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
