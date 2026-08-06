import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { tipApi, type TipCreatePayload, type TipView } from '@/api/tips'

export interface TipMessageContext {
  scopeType: string
  scopeId: string
  sourceMessageId: string
  sourceRole: string
  sourceContent: string
  agentPackageId?: string | null
  modelProfileId?: string | null
  reasoningIntensity?: number | null
}

export interface TipSelectionDraft extends TipMessageContext {
  selectedText: string
  selectionStart?: number | null
  selectionEnd?: number | null
}

export interface TipPanelOrigin {
  x: number
  y: number
}

export const useTipStore = defineStore('tips', () => {
  const tipsByScope = ref<Record<string, TipView[]>>({})
  const sources = ref<Record<string, TipMessageContext>>({})
  const activeTipByScope = ref<Record<string, string | null>>({})
  const draftByScope = ref<Record<string, TipSelectionDraft | null>>({})
  const openScopes = ref<string[]>([])
  const panelOrigins = ref<Record<string, TipPanelOrigin | null>>({})
  const panelLaunches = ref<Record<string, number>>({})
  const loadingScopes = ref<string[]>([])
  const errors = ref<Record<string, string | null>>({})

  const activeScopes = computed(() => new Set(openScopes.value))

  function scopeKey(scopeType: string, scopeId: string): string {
    return `${scopeType}:${scopeId}`
  }

  function sourceKey(context: Pick<TipMessageContext, 'scopeType' | 'scopeId' | 'sourceMessageId'>): string {
    return `${scopeKey(context.scopeType, context.scopeId)}:${context.sourceMessageId}`
  }

  function registerSource(context: TipMessageContext): string {
    const key = sourceKey(context)
    sources.value[key] = context
    return key
  }

  function unregisterSource(key: string): void {
    delete sources.value[key]
  }

  function hasSource(key: string): boolean {
    return Boolean(sources.value[key])
  }

  function beginSelection(key: string, selectedText: string, selectionStart?: number, selectionEnd?: number): void {
    const source = sources.value[key]
    const text = selectedText.trim()
    if (!source || !text) return
    const scope = scopeKey(source.scopeType, source.scopeId)
    draftByScope.value[scope] = {
      ...source,
      selectedText: text,
      selectionStart,
      selectionEnd,
    }
    activeTipByScope.value[scope] = null
    open(scope)
  }

  async function loadScope(scopeType: string, scopeId: string): Promise<void> {
    if (!scopeType || !scopeId) return
    const scope = scopeKey(scopeType, scopeId)
    if (!loadingScopes.value.includes(scope)) loadingScopes.value.push(scope)
    try {
      const response = await tipApi.list(scopeType, scopeId)
      tipsByScope.value[scope] = response.tips
      errors.value[scope] = null
    } catch (error) {
      errors.value[scope] = errorMessage(error)
    } finally {
      loadingScopes.value = loadingScopes.value.filter(item => item !== scope)
    }
  }

  async function createFromDraft(scopeType: string, scopeId: string, question: string): Promise<void> {
    const scope = scopeKey(scopeType, scopeId)
    const draft = draftByScope.value[scope]
    const prompt = question.trim()
    if (!draft || !prompt) return
    const temporaryId = `pending-${Date.now()}-${Math.random().toString(36).slice(2)}`
    const now = new Date().toISOString()
    const payload: TipCreatePayload = {
      scope_type: draft.scopeType,
      scope_id: draft.scopeId,
      source_message_id: draft.sourceMessageId,
      source_role: draft.sourceRole,
      source_content: draft.sourceContent,
      selected_text: draft.selectedText,
      question: prompt,
      selection_start: draft.selectionStart,
      selection_end: draft.selectionEnd,
      agent_package_id: draft.agentPackageId,
      model_profile_id: draft.modelProfileId,
      reasoning_intensity: draft.reasoningIntensity,
    }
    const pending: TipView = {
      tip_id: temporaryId,
      scope_type: draft.scopeType,
      scope_id: draft.scopeId,
      source_message_id: draft.sourceMessageId,
      source_role: draft.sourceRole,
      source_content: draft.sourceContent,
      selected_text: draft.selectedText,
      selection_start: draft.selectionStart,
      selection_end: draft.selectionEnd,
      agent_package_id: draft.agentPackageId,
      model_profile_id: draft.modelProfileId,
      reasoning_intensity: draft.reasoningIntensity,
      status: 'answering',
      messages: [{ message_id: `${temporaryId}-question`, role: 'user', content: prompt, created_at: now }],
      created_at: now,
      updated_at: now,
    }
    tipsByScope.value[scope] = [pending, ...(tipsByScope.value[scope] || [])]
    activeTipByScope.value[scope] = temporaryId
    draftByScope.value[scope] = null
    try {
      const response = await tipApi.create(payload)
      replaceTip(scope, temporaryId, response.tip)
      activeTipByScope.value[scope] = response.tip.tip_id
      errors.value[scope] = null
    } catch (error) {
      tipsByScope.value[scope] = (tipsByScope.value[scope] || []).filter(tip => tip.tip_id !== temporaryId)
      errors.value[scope] = errorMessage(error)
      await loadScope(scopeType, scopeId)
    }
  }

  async function followUp(scopeType: string, scopeId: string, tipId: string, question: string): Promise<void> {
    const scope = scopeKey(scopeType, scopeId)
    const prompt = question.trim()
    const current = tip(scopeType, scopeId, tipId)
    if (!current || !prompt || current.status === 'answering') return
    const optimistic: TipView = {
      ...current,
      status: 'answering',
      error: null,
      messages: [...current.messages, {
        message_id: `pending-${Date.now()}`,
        role: 'user',
        content: prompt,
        created_at: new Date().toISOString(),
      }],
    }
    replaceTip(scope, tipId, optimistic)
    try {
      const response = await tipApi.followUp(tipId, prompt)
      replaceTip(scope, tipId, response.tip)
      errors.value[scope] = null
    } catch (error) {
      errors.value[scope] = errorMessage(error)
      await loadScope(scopeType, scopeId)
    }
  }

  async function deleteTip(scopeType: string, scopeId: string, tipId: string): Promise<void> {
    const scope = scopeKey(scopeType, scopeId)
    await tipApi.delete(tipId)
    tipsByScope.value[scope] = (tipsByScope.value[scope] || []).filter(tip => tip.tip_id !== tipId)
    activeTipByScope.value[scope] = null
  }

  function tipsForSource(key: string): TipView[] {
    const source = sources.value[key]
    if (!source) return []
    return (tipsByScope.value[scopeKey(source.scopeType, source.scopeId)] || [])
      .filter(tip => tip.source_message_id === source.sourceMessageId)
  }

  function tip(scopeType: string, scopeId: string, tipId: string | null | undefined): TipView | null {
    if (!tipId) return null
    return (tipsByScope.value[scopeKey(scopeType, scopeId)] || []).find(item => item.tip_id === tipId) || null
  }

  function activeTip(scopeType: string, scopeId: string): TipView | null {
    const scope = scopeKey(scopeType, scopeId)
    return tip(scopeType, scopeId, activeTipByScope.value[scope])
  }

  function draft(scopeType: string, scopeId: string): TipSelectionDraft | null {
    return draftByScope.value[scopeKey(scopeType, scopeId)] || null
  }

  function selectTip(scopeType: string, scopeId: string, tipId: string, origin?: TipPanelOrigin): void {
    const scope = scopeKey(scopeType, scopeId)
    activeTipByScope.value[scope] = tipId
    draftByScope.value[scope] = null
    open(scope, origin)
  }

  function panelOrigin(scopeType: string, scopeId: string): TipPanelOrigin | null {
    return panelOrigins.value[scopeKey(scopeType, scopeId)] || null
  }

  function panelLaunchToken(scopeType: string, scopeId: string): number {
    return panelLaunches.value[scopeKey(scopeType, scopeId)] || 0
  }

  function isOpen(scopeType: string, scopeId: string): boolean {
    return activeScopes.value.has(scopeKey(scopeType, scopeId))
  }

  function close(scopeType: string, scopeId: string): void {
    const scope = scopeKey(scopeType, scopeId)
    openScopes.value = openScopes.value.filter(item => item !== scope)
    draftByScope.value[scope] = null
  }

  function open(scope: string, origin?: TipPanelOrigin): void {
    panelOrigins.value[scope] = origin || null
    panelLaunches.value[scope] = (panelLaunches.value[scope] || 0) + 1
    if (!openScopes.value.includes(scope)) openScopes.value.push(scope)
  }

  function replaceTip(scope: string, tipId: string, next: TipView): void {
    const current = tipsByScope.value[scope] || []
    const index = current.findIndex(item => item.tip_id === tipId)
    tipsByScope.value[scope] = index < 0
      ? [next, ...current]
      : current.map((item, itemIndex) => itemIndex === index ? next : item)
  }

  return {
    tipsByScope,
    loadingScopes,
    errors,
    scopeKey,
    sourceKey,
    registerSource,
    unregisterSource,
    hasSource,
    beginSelection,
    loadScope,
    createFromDraft,
    followUp,
    deleteTip,
    tipsForSource,
    activeTip,
    draft,
    selectTip,
    panelOrigin,
    panelLaunchToken,
    isOpen,
    close,
  }
})

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
