import type { WorkspaceContextInput, WorkspaceRequestContext } from './resourceTypes'


export type PackageResourceContext = Pick<WorkspaceRequestContext, 'packageId' | 'resourceMode'>


export function packageResourceContextPayload(
  context?: WorkspaceContextInput,
): { package_id?: string; resource_mode?: string } {
  const normalized = normalizePackageResourceContext(context)
  return {
    ...(normalized.packageId ? { package_id: normalized.packageId } : {}),
    ...(normalized.resourceMode ? { resource_mode: normalized.resourceMode } : {}),
  }
}


function normalizePackageResourceContext(context?: WorkspaceContextInput): PackageResourceContext {
  if (typeof context === 'string') return { packageId: context || undefined }
  if (!context) return {}
  return {
    packageId: context.packageId || undefined,
    resourceMode: context.resourceMode,
  }
}
