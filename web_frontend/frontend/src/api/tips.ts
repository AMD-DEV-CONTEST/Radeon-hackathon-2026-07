import { requestJson, withQuery } from './http'

export type TipStatus = 'answering' | 'completed' | 'failed'

export interface TipMessageView {
  message_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface TipView {
  tip_id: string
  scope_type: string
  scope_id: string
  source_message_id: string
  source_role: string
  source_content: string
  selected_text: string
  selection_start?: number | null
  selection_end?: number | null
  agent_package_id?: string | null
  model_profile_id?: string | null
  reasoning_intensity?: number | null
  status: TipStatus
  error?: string | null
  messages: TipMessageView[]
  created_at: string
  updated_at: string
}

export interface TipCreatePayload {
  scope_type: string
  scope_id: string
  source_message_id: string
  source_role: string
  source_content: string
  selected_text: string
  question: string
  selection_start?: number | null
  selection_end?: number | null
  agent_package_id?: string | null
  model_profile_id?: string | null
  reasoning_intensity?: number | null
}

export const tipApi = {
  list(scopeType: string, scopeId: string) {
    return requestJson<{ tips: TipView[] }>(withQuery('/api/tips', {
      scope_type: scopeType,
      scope_id: scopeId,
    }))
  },
  create(payload: TipCreatePayload) {
    return requestJson<{ tip: TipView }>('/api/tips', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  followUp(tipId: string, question: string) {
    return requestJson<{ tip: TipView }>(`/api/tips/${encodeURIComponent(tipId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ question }),
    })
  },
  delete(tipId: string) {
    return requestJson<{ deleted: boolean }>(`/api/tips/${encodeURIComponent(tipId)}`, {
      method: 'DELETE',
    })
  },
}
