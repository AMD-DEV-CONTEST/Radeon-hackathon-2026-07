import { cn } from '@/lib/utils'
import type { PersonaStatus } from '@/types'

type DotVariant = 'online' | 'offline' | 'warning' | 'idle' | PersonaStatus

const colors: Record<DotVariant, string> = {
  online:    'bg-green-500',
  offline:   'bg-red-500',
  warning:   'bg-amber-500',
  idle:      'bg-gray-300',
  attacking: 'bg-blue-500',
  hit:       'bg-amber-500',
  ok:        'bg-green-500',
  error:     'bg-red-500',
  skipped:   'bg-gray-300',
}

const pulse: Set<DotVariant> = new Set(['online', 'attacking'])

interface StatusDotProps {
  variant?: DotVariant
  size?: 'sm' | 'md'
  className?: string
}

export function StatusDot({ variant = 'idle', size = 'sm', className }: StatusDotProps) {
  const shouldPulse = pulse.has(variant)
  return (
    <span className={cn(
      'inline-block rounded-full flex-shrink-0',
      size === 'sm' ? 'w-1.5 h-1.5' : 'w-2 h-2',
      colors[variant] ?? 'bg-gray-300',
      shouldPulse && 'animate-pulse',
      className,
    )} />
  )
}
