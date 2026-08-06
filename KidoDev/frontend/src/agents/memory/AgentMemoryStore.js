/**
 * Agent Memory Store — Frontend
 * Short-term (in-memory) + long-term (Supabase) memory for the agent layer.
 */

const BACKEND_URL = import.meta.env.VITE_AGENT_BACKEND_URL || 'http://localhost:8000';
const isNgrok = BACKEND_URL.includes('ngrok');

// ─── Session Memory ────────────────────────────────────────────────────────────
// Tracks: current session ID, conversation history, hint count
const sessionState = {
  sessionId: null,
  childId: null,
  conversationHistory: [],  // [{role, content}]
  hintCount: 0,
  sessionStartMs: Date.now(),
  idleStartMs: Date.now(),
  blockPlacementsLastMinute: 0,
};

let _placementsThisMinute = 0;
let _placementResetInterval = null;

export function initSession(childId) {
  sessionState.childId = childId;
  sessionState.sessionId = `${childId}-${Date.now()}`;
  sessionState.conversationHistory = [];
  sessionState.hintCount = 0;
  sessionState.sessionStartMs = Date.now();
  sessionState.idleStartMs = Date.now();

  // Track block placements per minute for EngagementAgent
  clearInterval(_placementResetInterval);
  _placementResetInterval = setInterval(() => {
    sessionState.blockPlacementsLastMinute = _placementsThisMinute;
    _placementsThisMinute = 0;
  }, 60_000);

  return sessionState.sessionId;
}

export function recordBlockPlacedForEngagement() {
  _placementsThisMinute++;
  sessionState.idleStartMs = Date.now(); // reset idle timer on interaction
}

export function recordUserInteraction() {
  sessionState.idleStartMs = Date.now();
}

export function getSessionState() {
  return {
    ...sessionState,
    idleSeconds: Math.floor((Date.now() - sessionState.idleStartMs) / 1000),
    sessionDurationSeconds: Math.floor((Date.now() - sessionState.sessionStartMs) / 1000),
  };
}

export function addToConversation(role, content) {
  sessionState.conversationHistory.push({ role, content });
  if (sessionState.conversationHistory.length > 12) {
    sessionState.conversationHistory = sessionState.conversationHistory.slice(-12);
  }
}

export function getConversationHistory() {
  return [...sessionState.conversationHistory];
}

export function getSessionId() {
  return sessionState.sessionId;
}

export function getChildId() {
  return sessionState.childId;
}

export function incrementHintCount() {
  sessionState.hintCount += 1;
  return sessionState.hintCount;
}

export function getHintCount() {
  return sessionState.hintCount;
}

export async function clearRemoteSession() {
  const { childId, sessionId } = sessionState;
  if (!childId || !sessionId) return;
  try {
    const headers = {};
    if (isNgrok) headers['ngrok-skip-browser-warning'] = 'true';
    await fetch(`${BACKEND_URL}/agent/memory/${childId}/${sessionId}`, {
      method: 'DELETE',
      headers,
    });
  } catch { /* silent */ }
}
