import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import { SYSTEM_CHAT_PACKAGE_ID } from '@/utils/resourceScope'

export type ResourceTargetKind = 'chat' | 'create_agent' | 'evolve_agent' | 'package'

export interface ResourceTarget {
  kind: ResourceTargetKind
  packageId?: string
}

export type ResourceTargetCapability = 'package_only' | 'system_and_package'

export interface ResourceTargetOption {
  label: string
  value: string
}

export interface ResourceTargetOptionGroup {
  type: 'group'
  label: string
  key: string
  children: ResourceTargetOption[]
}

export function resourceTargetFromContext(context: WorkspaceRequestContext): ResourceTarget | null {
  if (context.resourceMode === 'create_agent') return { kind: 'create_agent' }
  if (context.resourceMode === 'evolve_agent') {
    return {
      kind: 'evolve_agent',
      packageId: normalizedValue(context.packageId),
    }
  }
  if (context.resourceMode === 'package' || !context.resourceMode) {
    const packageId = normalizedValue(context.packageId)
    return packageId && packageId !== SYSTEM_CHAT_PACKAGE_ID
      ? { kind: 'package', packageId }
      : { kind: 'chat' }
  }
  return null
}

export function resourceTargetKey(target: ResourceTarget): string {
  return target.kind === 'package'
    ? `package:${target.packageId || ''}`
    : target.kind
}

export function parseResourceTargetKey(value: string): ResourceTarget | null {
  if (value === 'chat' || value === 'create_agent' || value === 'evolve_agent') {
    return { kind: value }
  }
  if (!value.startsWith('package:')) return null
  const packageId = normalizedValue(value.slice('package:'.length))
  return packageId ? { kind: 'package', packageId } : null
}

function normalizedValue(value: unknown): string | undefined {
  return String(value || '').trim() || undefined
}
