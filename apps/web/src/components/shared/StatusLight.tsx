import type { ReactNode } from 'react'

export function StatusLight({
  label,
  ok,
  okIcon,
  badIcon,
  onClick,
}: {
  label: string
  ok: boolean
  okIcon: ReactNode
  badIcon: ReactNode
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-white/10 transition-colors"
      title={`${label}: ${ok ? '正常' : '不可用'}`}
    >
      <span className={ok ? 'text-emerald-300' : 'text-white/30'}>{ok ? okIcon : badIcon}</span>
      <span className={ok ? 'text-white/70' : 'text-white/30'}>{label}</span>
    </button>
  )
}
