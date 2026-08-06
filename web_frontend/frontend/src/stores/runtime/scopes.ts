import type { FactoryFrontendEvent, FactoryMode } from '@/types/protocol'

export interface AgentPackageScopeInfo {
  packageId: string
  sessionId: string
  scope: string
}

export function agentPackageConversationScope(
  packageId: string | null,
  sessionId: string | null,
): string {
  return `agent_package:${packageId || 'unknown'}:${sessionId || 'new'}`
}

export function conversationScopeForMode(
  mode: string | null,
  payload: Record<string, any> = {},
): string | null {
  if (mode === 'create_agent') return factoryConversationScope('create_agent', factorySessionIdFromPayload(payload))
  if (mode === 'evolve_agent') {
    const session = payload?.session && typeof payload.session === 'object' ? payload.session : {}
    const packageId =
      payload?.package_id ||
      payload?.evolve_agent_package_id ||
      payload?.package?.package_id ||
      session.evolve_agent_package_id
    return `factory:evolve_agent:${packageId || 'unselected'}:${factorySessionIdFromPayload(payload) || 'new'}`
  }
  return null
}

export function isMoreSpecificConversationScope(
  currentScope: string | null | undefined,
  nextScope: string | null | undefined,
): boolean {
  if (!currentScope || !nextScope || currentScope === nextScope) return false
  const currentParts = currentScope.split(':')
  const nextParts = nextScope.split(':')
  if (currentParts.length !== nextParts.length) return false
  if (currentParts[currentParts.length - 1] !== 'new') return false
  if (!nextParts[nextParts.length - 1] || nextParts[nextParts.length - 1] === 'new') return false
  return currentParts.slice(0, -1).join(':') === nextParts.slice(0, -1).join(':')
}

export function scopeFromEventPayload(event: FactoryFrontendEvent): string | null {
  if (event.mode === 'agent_package') {
    const agentSession = event.payload?.agent_session && typeof event.payload.agent_session === 'object'
      ? event.payload.agent_session
      : {}
    const loadedSession = event.payload?.session && typeof event.payload.session === 'object'
      ? event.payload.session
      : {}
    const packageId = String(event.payload?.package_id || agentSession.package_id || '').trim()
    const sessionId = String(event.payload?.session_id || agentSession.session_id || loadedSession.session_id || '').trim()
    if (packageId) {
      return agentPackageConversationScope(packageId, sessionId || null)
    }
  }
  return conversationScopeForMode(event.mode, {
    ...(event.payload || {}),
    session_id: event.session_id || event.payload?.session_id,
  })
}

export function agentPackageScopeInfoFromEvent(event: FactoryFrontendEvent): AgentPackageScopeInfo | null {
  if (event.mode !== 'agent_package') return null
  const agentSession = event.payload?.agent_session && typeof event.payload.agent_session === 'object'
    ? event.payload.agent_session
    : {}
  const loadedSession = event.payload?.session && typeof event.payload.session === 'object'
    ? event.payload.session
    : {}
  const packageId = String(event.payload?.package_id || agentSession.package_id || '').trim()
  const sessionId = String(event.payload?.session_id || agentSession.session_id || loadedSession.session_id || '').trim()
  if (!packageId || !sessionId) return null
  return {
    packageId,
    sessionId,
    scope: agentPackageConversationScope(packageId, sessionId),
  }
}

export function scopeFromRequestPayload(
  mode: FactoryMode | null,
  payload: Record<string, any>,
): string | null {
  if (mode !== 'agent_package') {
    return conversationScopeForMode(mode, payload)
  }
  const packageId = cleanText(payload.package_id)
  if (!packageId) return null
  return agentPackageConversationScope(packageId, cleanText(payload.session_id))
}

export function scopeFromMessageMetadata(
  metadata: Record<string, any>,
  currentMode: FactoryMode | null,
  activeFactorySessionId: string | null = null,
): string | null {
  const mode = String(metadata.mode || currentMode || '')
  if (mode === 'agent_package') {
    return agentPackageConversationScope(
      metadata.package_id ? String(metadata.package_id) : null,
      metadata.agent_session_id ? String(metadata.agent_session_id) : null,
    )
  }
  return conversationScopeForMode(mode, {
    ...metadata,
    session_id: metadata.session_id || metadata.factory_session_id || activeFactorySessionId,
  })
}

function factoryConversationScope(mode: string, sessionId: string | null): string {
  return `factory:${mode}:${sessionId || 'new'}`
}

function factorySessionIdFromPayload(payload: Record<string, any>): string | null {
  const session = payload?.session && typeof payload.session === 'object' ? payload.session : {}
  const value = payload?.session_id || payload?.factory_session_id || payload?.frontend_session_id || session.session_id
  const text = String(value || '').trim()
  return text || null
}

function cleanText(value: unknown): string | null {
  const text = String(value || '').trim()
  return text || null
}
