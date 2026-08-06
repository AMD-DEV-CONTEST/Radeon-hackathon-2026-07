// drafts.ts — draft-answer lifecycle (Todo 9).
//
// Drafts are keyed in sessionStorage by the DURABLE server session ID + unit ID
// (never a bare route), so a refresh restores the same draft and a different
// session can never see it. Submit/abandon clear the key atomically.

const PREFIX = "lc:draft"

export function draftKey(sessionId: number, unitId: number): string {
  return `${PREFIX}:${sessionId}:${unitId}`
}

export function saveDraft(sessionId: number, unitId: number, text: string): void {
  try {
    sessionStorage.setItem(draftKey(sessionId, unitId), text)
  } catch {
    /* storage unavailable: drafts are best-effort */
  }
}

export function loadDraft(sessionId: number, unitId: number): string {
  try {
    return sessionStorage.getItem(draftKey(sessionId, unitId)) ?? ""
  } catch {
    return ""
  }
}

export function clearDraft(sessionId: number, unitId: number): void {
  try {
    sessionStorage.removeItem(draftKey(sessionId, unitId))
  } catch {
    /* best-effort */
  }
}

export function clearSessionDrafts(sessionId: number): void {
  try {
    const prefix = `${PREFIX}:${sessionId}:`
    for (let i = 0; i < sessionStorage.length; i++) {
      const k = sessionStorage.key(i)
      if (k && k.startsWith(prefix)) sessionStorage.removeItem(k)
    }
  } catch {
    /* best-effort */
  }
}
