import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { RiskBand, Tier } from '@/types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatRisk(risk: number): string {
  return (risk * 100).toFixed(0)
}

export function formatUtility(util: number): string {
  return (util * 100).toFixed(1) + '%'
}

export function formatElapsed(s: number): string {
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return `${m}m ${rem.toFixed(0)}s`
}

export function formatDate(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
    hour12: false,
  })
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function bandColor(band: RiskBand): string {
  switch (band) {
    case 'CRITICAL': return 'text-red-700'
    case 'HIGH':     return 'text-amber-700'
    case 'MEDIUM':   return 'text-sky-700'
    case 'LOW':      return 'text-green-700'
  }
}

export function bandBgColor(band: RiskBand): string {
  switch (band) {
    case 'CRITICAL': return 'bg-red-50 text-red-700 border-red-200'
    case 'HIGH':     return 'bg-amber-50 text-amber-700 border-amber-200'
    case 'MEDIUM':   return 'bg-sky-50 text-sky-700 border-sky-200'
    case 'LOW':      return 'bg-green-50 text-green-700 border-green-200'
  }
}

export function tierBgColor(tier: Tier): string {
  switch (tier) {
    case 'M': return 'bg-amber-50 text-amber-700 border-amber-200'
    case 'C': return 'bg-red-50 text-red-700 border-red-200'
    case 'S': return 'bg-gray-100 text-gray-600 border-gray-200'
  }
}

export function tierLabel(tier: Tier): string {
  switch (tier) {
    case 'M': return 'Mechanical'
    case 'C': return 'Correlational'
    case 'S': return 'Stylistic'
  }
}

export function tierBorderColor(tier: Tier): string {
  switch (tier) {
    case 'M': return 'border-l-amber-400'
    case 'C': return 'border-l-red-500'
    case 'S': return 'border-l-gray-300'
  }
}

export function riskToPercent(risk: number): number {
  return Math.min(100, Math.max(0, risk * 100))
}

export function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s
}

export function now(): number {
  return Math.floor(Date.now() / 1000)
}
