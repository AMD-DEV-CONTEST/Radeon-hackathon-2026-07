/**
 * Agent Store
 * 管理 Agent 包和子会话
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { isStandaloneAgentSession } from '@/utils/sessionPresentation'
import { SYSTEM_CHAT_PACKAGE_ID } from '@/utils/resourceScope'

export interface AgentPackageToolView {
  kind?: string
  id?: string
  name: string
  description?: string
  risk_level?: string
  concurrent?: boolean
}

export interface AgentPackageExtensionView {
  kind?: 'mcp' | 'skill' | string
  name: string
  scope?: string
  status?: string
  enabled?: boolean
  summary?: string
  transport?: string | null
  payload?: Record<string, any>
}

export interface AgentPackageKnowledgeSourceView {
  source_id?: string
  name: string
  kind?: string | null
  status?: string | null
  mode?: string | null
  uri?: string | null
  updated_at?: string | null
  document_count?: number | null
  sample_titles?: string[]
}

export interface AgentPackageInstanceView {
  package_id: string
  agent_id?: string | null
  agent_name?: string | null
  backend?: string | null
  status: string
  ready: boolean
  active_request_count?: number
  runtime_root?: string | null
  idle_timeout_seconds?: number | null
  error?: string | null
}

export interface AgentPackageModelContractView {
  version: string
  bindings: Record<string, {
    profile_id?: string
    source?: 'model_pool' | 'runtime' | string
    selection_source?: string
    reason?: string
    required_capabilities?: Record<string, any>
    overrides?: Record<string, any>
  }>
  tool_bindings?: Record<string, {
    profile_id?: string
    source?: 'model_pool' | 'env' | string
    capability?: string
    selection_source?: string
    reason?: string
    description?: string
    required_capabilities?: Record<string, any>
    overrides?: Record<string, any>
  }>
}

export interface AgentPackageContextContractView {
  version: string
  enabled?: boolean
  config?: Record<string, any>
  context_window_tokens?: number | null
  context_window_tokens_source?: string | null
  compression_threshold_tokens?: number | null
  compression_threshold_tokens_source?: string | null
  model_profile_id?: string | null
  error?: string | null
}

export interface AgentPackageSchedulerContractView {
  version: string
  enabled: boolean
  config: {
    store_backend: 'sqlite'
    store_path: string
    timezone: string
    default_concurrency_policy: 'skip' | 'queue' | 'replace'
    default_timeout_seconds: number
    unattended_policy: 'deny_if_approval_required' | 'pause_and_wait_for_user' | 'allow_preapproved_only'
    default_failure_policy: {
      enabled: boolean
      max_consecutive_failures: number
      action: 'pause'
    }
  }
}

export interface AgentPackageView {
  package_id: string
  package_path?: string
  manifest_path?: string
  package_origin?: 'system' | 'user'
  is_builtin?: boolean
  capabilities?: {
    deletable?: boolean
    exportable?: boolean
  }
  factory_run_id?: string | null
  agent_id?: string | null
  agent_name: string | null
  name: string | null
  agent_description: string | null
  runtime_pattern_id?: string | null
  status: string | null
  tool_count: number | null
  session_count: number | null
  created_at: string | null
  updated_at: string | null
  sandbox?: Record<string, any>
  model_contract?: AgentPackageModelContractView
  context_contract?: AgentPackageContextContractView
  scheduler_contract?: AgentPackageSchedulerContractView
  resources?: { key_available: boolean; resources: Array<{ resource_id: string; configured: boolean }>; migration?: { status: string } }
  environment?: { status?: string; image?: string; image_digest?: string; platform?: Record<string, string>; verified_at?: string; error?: string }
  extensions?: Record<string, any>
  tools?: AgentPackageToolView[]
  mcp_servers?: AgentPackageExtensionView[]
  skills?: AgentPackageExtensionView[]
  knowledge_sources?: AgentPackageKnowledgeSourceView[]
  extensions_error?: string | null
  knowledge_error?: string | null
  error?: string | null
}

export interface AgentSessionView {
  session_id: string
  workspace_id?: string | null
  workspace?: {
    workspace_id: string
    title: string
    mode: 'isolated' | 'project'
    root_kind: 'managed' | 'linked'
    workdir_root: string
  } | null
  package_id: string
  session_kind?: string | null
  visible_in_agent_session_list?: boolean | null
  display_title: string | null
  first_user_input: string | null
  turn_count: number
  created_at: string
  updated_at: string
}

export interface AgentRecentSessionView extends AgentSessionView {
  package_name?: string | null
  agent_name?: string | null
}

const LAST_AGENT_SESSION_STORAGE_KEY = 'fastagentfactory.lastAgentSession'

interface LastAgentSessionSelection {
  packageId: string
  sessionId: string | null
}

export const useAgentStore = defineStore('agent', () => {
  const agentPackages = ref<AgentPackageView[]>([])
  const packageInstances = ref<Record<string, AgentPackageInstanceView>>({})
  const selectedPackageId = ref<string | null>(null)
  const agentSessions = ref<AgentSessionView[]>([])
  const recentAgentSessions = ref<AgentRecentSessionView[]>([])
  const selectedSessionId = ref<string | null>(null)
  const activeChatPackageId = ref<string | null>(null)
  const lastAgentSession = ref<LastAgentSessionSelection | null>(loadLastAgentSession())

  const selectedPackage = computed(() => {
    if (!selectedPackageId.value) return null
    return agentPackages.value.find((pkg) => pkg.package_id === selectedPackageId.value) || null
  })

  const selectedSession = computed(() => {
    if (!selectedSessionId.value) return null
    return agentSessions.value.find((session) => session.session_id === selectedSessionId.value) || null
  })

  const activeChatPackage = computed(() => {
    if (!activeChatPackageId.value) return null
    return agentPackages.value.find((pkg) => pkg.package_id === activeChatPackageId.value) || null
  })

  const selectedPackageInstance = computed(() => {
    if (!selectedPackageId.value) return null
    return packageInstances.value[selectedPackageId.value] || null
  })

  function packageInstance(packageId: string | null | undefined): AgentPackageInstanceView | null {
    if (!packageId) return null
    return packageInstances.value[packageId] || null
  }

  function setPackages(packages: AgentPackageView[]): void {
    agentPackages.value = packages
    if (
      selectedPackageId.value &&
      !agentPackages.value.some((pkg) => pkg.package_id === selectedPackageId.value)
    ) {
      selectedPackageId.value = null
      selectedSessionId.value = null
      agentSessions.value = []
    }
    if (
      activeChatPackageId.value &&
      !agentPackages.value.some((pkg) => pkg.package_id === activeChatPackageId.value)
    ) {
      activeChatPackageId.value = null
      selectedSessionId.value = null
    }
    filterRecentSessionsByPackages()
  }

  function setInstances(instances: AgentPackageInstanceView[]): void {
    packageInstances.value = Object.fromEntries(
      instances
        .filter((item) => item.package_id)
        .map((item) => [item.package_id, item])
    )
  }

  function upsertInstance(instance: AgentPackageInstanceView): void {
    if (!instance.package_id) return
    packageInstances.value = {
      ...packageInstances.value,
      [instance.package_id]: instance,
    }
  }

  function selectPackage(packageId: string): void {
    const packageChanged = selectedPackageId.value !== packageId
    selectedPackageId.value = packageId
    if (packageChanged) {
      selectedSessionId.value = null
      agentSessions.value = []
    }
  }

  function setSessions(sessions: AgentSessionView[], packageId?: string | null): void {
    const fallbackPackageId = String(packageId || '').trim()
    agentSessions.value = sessions
      .map((session) => ({
        ...session,
        package_id: String(session.package_id || fallbackPackageId).trim(),
      }))
      .filter((session) => Boolean(session.package_id) && isStandaloneAgentSession(session))
    if (
      selectedSessionId.value
      && !agentSessions.value.some((session) => session.session_id === selectedSessionId.value)
    ) {
      selectedSessionId.value = null
    }
  }

  function setRecentSessions(sessions: AgentRecentSessionView[]): void {
    recentAgentSessions.value = normalizeRecentSessions(sessions)
    validateLastAgentSession()
  }

  function mergeRecentSessions(sessions: AgentRecentSessionView[]): void {
    recentAgentSessions.value = normalizeRecentSessions([
      ...sessions,
      ...recentAgentSessions.value,
    ])
  }

  function selectSession(sessionId: string | null): void {
    selectedSessionId.value = sessionId
    if (activeChatPackageId.value) rememberAgentSession(activeChatPackageId.value, sessionId)
  }

  function removeSession(sessionId: string): void {
    agentSessions.value = agentSessions.value.filter((session) => session.session_id !== sessionId)
    recentAgentSessions.value = recentAgentSessions.value.filter((session) => session.session_id !== sessionId)
    if (selectedSessionId.value === sessionId) {
      selectedSessionId.value = null
    }
    if (lastAgentSession.value?.sessionId === sessionId) {
      const packageId = lastAgentSession.value.packageId
      const fallback = recentAgentSessions.value.find((session) => session.package_id === packageId)
      rememberAgentSession(packageId, fallback?.session_id || null)
    }
  }

  function removeRecentSessionsForPackage(packageId: string): void {
    recentAgentSessions.value = recentAgentSessions.value.filter((session) => session.package_id !== packageId)
  }

  function enterAgentChat(packageId: string, sessionId: string | null = null): void {
    activeChatPackageId.value = packageId
    selectedPackageId.value = packageId
    selectedSessionId.value = sessionId
    rememberAgentSession(packageId, sessionId)
  }

  function leaveAgentChat(): void {
    activeChatPackageId.value = null
    selectedSessionId.value = null
  }

  function setActiveAgentSession(sessionId: string | null): void {
    selectedSessionId.value = sessionId
    if (activeChatPackageId.value) rememberAgentSession(activeChatPackageId.value, sessionId)
  }

  function addPackage(pkg: AgentPackageView): void {
    const existingIndex = agentPackages.value.findIndex((p) => p.package_id === pkg.package_id)
    if (existingIndex !== -1) {
      agentPackages.value[existingIndex] = pkg
    } else {
      agentPackages.value.unshift(pkg)
    }
  }

  function removePackage(packageId: string): void {
    const index = agentPackages.value.findIndex((p) => p.package_id === packageId)
    if (index !== -1) {
      agentPackages.value.splice(index, 1)
    }
    if (selectedPackageId.value === packageId) {
      selectedPackageId.value = null
    }
    if (activeChatPackageId.value === packageId) {
      activeChatPackageId.value = null
      selectedSessionId.value = null
    }
    if (lastAgentSession.value?.packageId === packageId) {
      rememberAgentSession('', null)
    }
    recentAgentSessions.value = recentAgentSessions.value.filter((session) => session.package_id !== packageId)
  }

  function normalizeRecentSessions(sessions: AgentRecentSessionView[]): AgentRecentSessionView[] {
    const byKey = new Map<string, AgentRecentSessionView>()
    sessions
      .filter((session) => (
        session.package_id
        && session.package_id !== SYSTEM_CHAT_PACKAGE_ID
        && session.session_id
        && isStandaloneAgentSession(session)
      ))
      .forEach((session) => {
        byKey.set(`${session.package_id}:${session.session_id}`, session)
      })
    return [...byKey.values()]
      .sort((left, right) => sessionTime(right).localeCompare(sessionTime(left)))
      .slice(0, 5)
  }

  function sessionTime(session: AgentRecentSessionView): string {
    return session.updated_at || session.created_at || ''
  }

  function filterRecentSessionsByPackages(): void {
    const packageIds = new Set(agentPackages.value.map((pkg) => pkg.package_id))
    recentAgentSessions.value = recentAgentSessions.value.filter((session) => packageIds.has(session.package_id))
  }

  function preferredRecentSession(): AgentRecentSessionView | null {
    const persisted = lastAgentSession.value
    if (persisted?.sessionId) {
      const match = recentAgentSessions.value.find((session) => (
        session.package_id === persisted.packageId && session.session_id === persisted.sessionId
      ))
      if (match) return match
    }
    return recentAgentSessions.value[0] || null
  }

  function validateLastAgentSession(): void {
    if (!lastAgentSession.value?.sessionId) return
    const exists = recentAgentSessions.value.some((session) => (
      session.package_id === lastAgentSession.value?.packageId
      && session.session_id === lastAgentSession.value?.sessionId
    ))
    if (!exists) {
      const fallback = recentAgentSessions.value[0]
      rememberAgentSession(fallback?.package_id || '', fallback?.session_id || null)
    }
  }

  function rememberAgentSession(packageId: string, sessionId: string | null): void {
    const normalizedPackageId = String(packageId || '').trim()
    if (!normalizedPackageId) {
      lastAgentSession.value = null
      localStorage.removeItem(LAST_AGENT_SESSION_STORAGE_KEY)
      return
    }
    lastAgentSession.value = { packageId: normalizedPackageId, sessionId }
    localStorage.setItem(LAST_AGENT_SESSION_STORAGE_KEY, JSON.stringify(lastAgentSession.value))
  }

  return {
    agentPackages,
    packageInstances,
    selectedPackageId,
    agentSessions,
    recentAgentSessions,
    selectedSessionId,
    activeChatPackageId,
    lastAgentSession,
    selectedPackage,
    selectedSession,
    activeChatPackage,
    selectedPackageInstance,
    packageInstance,
    setPackages,
    setInstances,
    upsertInstance,
    selectPackage,
    setSessions,
    setRecentSessions,
    mergeRecentSessions,
    selectSession,
    removeSession,
    removeRecentSessionsForPackage,
    enterAgentChat,
    leaveAgentChat,
    setActiveAgentSession,
    preferredRecentSession,
    addPackage,
    removePackage,
  }
})

function loadLastAgentSession(): LastAgentSessionSelection | null {
  try {
    const payload = JSON.parse(localStorage.getItem(LAST_AGENT_SESSION_STORAGE_KEY) || 'null')
    const packageId = String(payload?.packageId || '').trim()
    if (!packageId) return null
    const sessionId = String(payload?.sessionId || '').trim() || null
    return { packageId, sessionId }
  } catch {
    localStorage.removeItem(LAST_AGENT_SESSION_STORAGE_KEY)
    return null
  }
}
