export interface SessionDeletion {
  sessionIds: string[]
  deletedActive: boolean
}

export function sessionDeletionFromPayload(payload: Record<string, any> | undefined): SessionDeletion {
  const rawSessionIds = Array.isArray(payload?.session_ids) ? payload.session_ids : []
  const sessionIds = [...rawSessionIds, payload?.session_id]
    .map((value) => String(value || '').trim())
    .filter(Boolean)

  return {
    sessionIds: [...new Set(sessionIds)],
    deletedActive: payload?.deleted_active === true,
  }
}

export function sessionDeletionIncludes(
  deletion: SessionDeletion,
  sessionId: string | null | undefined,
): boolean {
  const normalizedSessionId = String(sessionId || '').trim()
  return Boolean(normalizedSessionId && deletion.sessionIds.includes(normalizedSessionId))
}
