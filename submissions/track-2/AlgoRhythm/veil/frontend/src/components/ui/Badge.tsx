import { cn } from '@/lib/utils'
import type { RiskBand, Tier } from '@/types'
import { bandBgColor, tierBgColor, tierLabel } from '@/lib/utils'

interface BadgeProps {
  children: React.ReactNode
  className?: string
}

export function Badge({ children, className }: BadgeProps) {
  return (
    <span className={cn(
      'inline-flex items-center px-2 py-0.5 rounded text-2xs font-medium border',
      className
    )}>
      {children}
    </span>
  )
}

export function RiskBadge({ band }: { band: RiskBand }) {
  return (
    <Badge className={cn('font-mono tracking-wide uppercase', bandBgColor(band))}>
      {band}
    </Badge>
  )
}

export function TierBadge({ tier }: { tier: Tier }) {
  return (
    <Badge className={cn('font-mono', tierBgColor(tier))}>
      {tierLabel(tier)}
    </Badge>
  )
}

export function PersonaBadge({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-2xs font-mono text-gray-500 bg-gray-100 border border-gray-200">
      {name}
    </span>
  )
}
