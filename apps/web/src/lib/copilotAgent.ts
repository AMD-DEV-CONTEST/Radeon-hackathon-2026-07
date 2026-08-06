/** Client-side actions the Copilot agent can trigger (not just LLM text). */

export type ReachyActionIntent =
  | 'goto'
  | 'play_emotion'
  | 'play_dance'
  | 'start_chat'
  | 'start_head_tracker'

export type CopilotAction =
  | { type: 'navigate'; href: string; label: string }
  | { type: 'run_diagnose'; label: string }
  | { type: 'start_product_tour'; label: string }
  | { type: 'start_reachy_guide'; label: string }
  | { type: 'open_tab'; tab: 'diagnose' | 'chat'; label: string }
  | { type: 'reachy_virtual_start'; label: string }
  | { type: 'reachy_play_demo'; label: string }
  // M26 — robot-driving actions emitted by the agent when on /robots/reachy_mini.
  // The handler is registered by RobotReachyMini.tsx and dispatches to reachyApi.
  | { type: 'reachy_goto'; pitch?: number; yaw?: number; roll?: number; bodyYaw?: number; duration?: number; label: string }
  | { type: 'reachy_play_emotion'; emotion: string; label: string }
  | { type: 'reachy_play_dance'; dance: string; label: string }
  | { type: 'reachy_start_chat'; message?: string; label: string }
  | { type: 'reachy_start_head_tracker'; label: string }
  | { type: 'b601_run_health_check'; label: string }
  | { type: 'b601_run_recover'; label: string }
  | { type: 'b601_start_guide'; label: string }
  | { type: 'b601_install_local_agent'; label: string }

// Handlers may optionally receive the action payload (used by M26 robot-driving
// actions to forward params to reachyApi).
export type CopilotActionHandler = (action?: CopilotAction) => void | Promise<void>

const handlers = new Map<string, CopilotActionHandler>()

export function registerCopilotActionHandler(
  type: string,
  fn: CopilotActionHandler,
): () => void {
  handlers.set(type, fn)
  return () => handlers.delete(type)
}

export async function executeCopilotAction(action: CopilotAction): Promise<boolean> {
  switch (action.type) {
    case 'navigate':
      window.location.href = action.href
      return true
    case 'run_diagnose':
      window.dispatchEvent(new CustomEvent('botversex:copilot', { detail: { tab: 'diagnose' } }))
      return true
    case 'start_product_tour':
      window.dispatchEvent(new CustomEvent('botversex:start-tour'))
      return true
    case 'start_reachy_guide': {
      const onReachy = window.location.pathname.includes('reachy')
      window.dispatchEvent(
        new CustomEvent('botversex:start-reachy-guide', {
          detail: onReachy ? { preset: 'virtual' as const } : {},
        }),
      )
      return true
    }
    case 'open_tab':
      window.dispatchEvent(
        new CustomEvent('botversex:copilot', { detail: { tab: action.tab } }),
      )
      return true
    // M26 — robot-driving actions: pass the action payload to the registered
    // handler so it can call the matching reachyApi function with the params.
    case 'reachy_goto':
    case 'reachy_play_emotion':
    case 'reachy_play_dance':
    case 'reachy_start_chat':
    case 'reachy_start_head_tracker':
    case 'reachy_virtual_start':
    case 'reachy_play_demo': {
      const fn = handlers.get(action.type)
      if (fn) {
        await fn(action)
        return true
      }
      return false
    }
    default: {
      const fn = handlers.get((action as { type: string }).type)
      if (fn) {
        await fn(action)
        return true
      }
      return false
    }
  }
}

export interface CopilotOpenDetail {
  tab?: 'diagnose' | 'chat'
  prefill?: string
  open?: boolean
}

/** Close page tours / spotlight overlays so the assistant panel is usable. */
export function dismissActiveGuides() {
  window.dispatchEvent(new CustomEvent('botversex:dismiss-guides'))
}

export function openCopilot(detail: CopilotOpenDetail = {}) {
  dismissActiveGuides()
  window.dispatchEvent(new CustomEvent('botversex:copilot', { detail: { open: true, ...detail } }))
}
