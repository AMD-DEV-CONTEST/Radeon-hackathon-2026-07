export interface SessionPresentationMetadata {
  visible_in_agent_session_list?: boolean | null
  visible_in_factory_session_list?: boolean | null
}

export function isStandaloneAgentSession(session: SessionPresentationMetadata): boolean {
  return session.visible_in_agent_session_list !== false
}

export function isStandaloneFactorySession(session: SessionPresentationMetadata): boolean {
  return session.visible_in_factory_session_list !== false
}
