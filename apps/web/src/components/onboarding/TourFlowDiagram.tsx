import { Bot, Camera, Cloud, Cpu, Gamepad2, Monitor, Sparkles } from 'lucide-react'
import type { TourVisual } from './tours'

interface Props {
  variant: TourVisual
  className?: string
}

function Node({
  icon: Icon,
  label,
  sub,
  accent,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  sub?: string
  accent?: boolean
}) {
  return (
    <div
      className={`flex flex-col items-center gap-1.5 rounded-xl border px-4 py-3 min-w-[88px] ${
        accent
          ? 'border-[hsl(var(--primary))]/60 bg-[hsl(var(--primary))]/15 shadow-[0_0_24px_-4px_hsl(var(--primary)/0.4)]'
          : 'border-[hsl(var(--border))]/70 bg-[hsl(var(--card))]/80'
      }`}
    >
      <div
        className={`flex h-10 w-10 items-center justify-center rounded-lg ${
          accent ? 'bg-[hsl(var(--primary))]/25' : 'bg-[hsl(var(--muted))]/50'
        }`}
      >
        <Icon className={`h-5 w-5 ${accent ? 'text-[hsl(var(--primary))]' : 'text-[hsl(var(--muted-foreground))]'}`} />
      </div>
      <span className="text-xs font-semibold text-[hsl(var(--foreground))]">{label}</span>
      {sub && <span className="text-[10px] text-[hsl(var(--muted-foreground))]">{sub}</span>}
    </div>
  )
}

function Arrow({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5 px-1 shrink-0">
      <svg width="48" height="20" viewBox="0 0 48 20" className="text-[hsl(var(--primary))]">
        <path
          d="M2 10 H38 M32 5 L40 10 L32 15"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="tour-arrow-dash"
        />
      </svg>
      {label && (
        <span className="text-[9px] text-[hsl(var(--muted-foreground))] whitespace-nowrap">{label}</span>
      )}
    </div>
  )
}

function OverviewDiagram() {
  return (
    <div className="flex flex-col items-center gap-4 w-full">
      <div className="flex items-center justify-center flex-wrap gap-2 sm:gap-0">
        <Node icon={Monitor} label="你的浏览器" sub="打开网站" />
        <Arrow label="HTTPS" />
        <Node icon={Cloud} label="BotverseX 云端" sub="训练·模型" accent />
        <Arrow label="Local Agent" />
        <Node icon={Bot} label="你的电脑" sub="USB·串口·摄像头" accent />
      </div>
      <div className="flex items-center gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
        <Camera className="h-3.5 w-3.5" />
        <span>机械臂和摄像头在你电脑上，网站负责管理和训练</span>
      </div>
    </div>
  )
}

const WIZARD_STEPS = [
  { icon: Cpu, label: '连接', color: 'text-sky-400' },
  { icon: Gamepad2, label: '遥操作', color: 'text-violet-400' },
  { icon: Camera, label: '录制', color: 'text-amber-400' },
  { icon: Sparkles, label: '训练推理', color: 'text-emerald-400' },
] as const

function WizardDiagram() {
  return (
    <div className="flex flex-col items-center gap-3 w-full">
      <div className="flex items-center justify-center flex-wrap gap-1">
        {WIZARD_STEPS.map((step, i) => {
          const Icon = step.icon
          return (
            <div key={step.label} className="flex items-center">
              <div className="flex flex-col items-center gap-1 rounded-xl border border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/60 px-3 py-2.5 min-w-[72px] tour-step-pop" style={{ animationDelay: `${i * 120}ms` }}>
                <Icon className={`h-6 w-6 ${step.color}`} />
                <span className="text-[11px] font-medium">{step.label}</span>
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[hsl(var(--primary))]/20 text-[10px] font-bold text-[hsl(var(--primary))]">
                  {i + 1}
                </span>
              </div>
              {i < WIZARD_STEPS.length - 1 && (
                <svg width="28" height="16" viewBox="0 0 28 16" className="text-[hsl(var(--primary))]/70 mx-0.5">
                  <path d="M2 8 H20 M16 4 L22 8 L16 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" className="tour-arrow-dash" />
                </svg>
              )}
            </div>
          )
        })}
      </div>
      <p className="text-[11px] text-[hsl(var(--muted-foreground))] text-center">
        向导会<strong className="text-[hsl(var(--foreground))]">高亮当前步骤</strong>，做完一步解锁下一步
      </p>
    </div>
  )
}

function PathsDiagram() {
  return (
    <div className="grid sm:grid-cols-2 gap-3 w-full text-left">
      <div className="rounded-xl border-2 border-[hsl(var(--primary))]/50 bg-[hsl(var(--primary))]/10 p-4 space-y-2">
        <div className="text-xs font-bold text-[hsl(var(--primary))]">A · 有机械臂</div>
        <div className="flex flex-col gap-1.5 text-[11px]">
          {['Setup 装 Agent', 'Robots', '进入向导', '4 步闭环'].map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--primary))]/25 text-[10px] font-bold text-[hsl(var(--primary))]">
                {i + 1}
              </span>
              <span className="text-[hsl(var(--foreground))]">{s}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-xl border border-[hsl(var(--border))]/70 bg-[hsl(var(--card))]/60 p-4 space-y-2">
        <div className="text-xs font-bold text-[hsl(var(--muted-foreground))]">B · 没机械臂</div>
        <div className="flex flex-col gap-1.5 text-[11px] text-[hsl(var(--muted-foreground))]">
          <span>→ Reachy 虚拟模式</span>
          <span>→ 或只浏览网站</span>
        </div>
      </div>
    </div>
  )
}

export function TourFlowDiagram({ variant, className = '' }: Props) {
  return (
    <div className={`w-full ${className}`}>
      {variant === 'overview' && <OverviewDiagram />}
      {variant === 'wizard' && <WizardDiagram />}
      {variant === 'paths' && <PathsDiagram />}
      {variant === 'connect' && <OverviewDiagram />}
    </div>
  )
}
