import { workspaceApi } from '@/api/workspace'
import type { WorkspaceRequestContext, WorkspaceScope } from '@/api/resourceTypes'

const WORKSPACE_SCOPES = new Set<WorkspaceScope>([
  'package',
  'runtime',
  'workdir',
  'artifacts',
  'extensions',
])

const IMAGE_EXTENSIONS = new Set([
  'avif',
  'bmp',
  'gif',
  'jpeg',
  'jpg',
  'png',
  'svg',
  'webp',
])

export interface WorkspaceFileReference {
  scope: WorkspaceScope
  path: string
}

export function isImageResource(nameOrPath: string, mimeType?: string | null): boolean {
  if (String(mimeType || '').toLowerCase().startsWith('image/')) return true
  const path = resourcePathname(nameOrPath)
  const extension = path.split('/').pop()?.split('.').pop()?.toLowerCase() || ''
  return IMAGE_EXTENSIONS.has(extension)
}

export function workspaceFileReference(
  source: string,
  defaultScope: WorkspaceScope = 'workdir',
): WorkspaceFileReference | null {
  const normalized = resourcePathname(source).replace(/\\/g, '/').trim()
  if (!normalized || normalized.startsWith('//') || hasUriScheme(normalized)) return null

  if (normalized.split('/').some(part => part === '..')) return null
  const parts = normalized.split('/').filter(part => Boolean(part) && part !== '.')
  if (!parts.length) return null

  const explicitScope = WORKSPACE_SCOPES.has(parts[0] as WorkspaceScope)
    ? parts.shift() as WorkspaceScope
    : null
  if (normalized.startsWith('/') && !explicitScope) return null
  if (!parts.length) return null

  return {
    scope: explicitScope || defaultScope,
    path: parts.join('/'),
  }
}

export function workspaceResourceUrl(
  source: string,
  context: WorkspaceRequestContext | null | undefined,
  defaultScope: WorkspaceScope = 'workdir',
): string | null {
  const normalized = String(source || '').trim()
  if (!normalized) return null
  if (isRemoteImage(normalized)) return normalized

  const reference = workspaceFileReference(normalized, defaultScope)
  if (!reference || !context) return null
  return workspaceApi.rawUrl(reference.scope, reference.path, context)
}

function resourcePathname(source: string): string {
  return String(source || '').split('#', 1)[0].split('?', 1)[0]
}

function hasUriScheme(source: string): boolean {
  return /^[a-z][a-z\d+.-]*:/i.test(source)
}

function isRemoteImage(source: string): boolean {
  return /^https?:\/\//i.test(source) || source.startsWith('//')
}
