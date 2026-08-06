import type {
  AgentPackageExtensionView,
  AgentPackageInstanceView,
  AgentPackageKnowledgeSourceView,
  AgentPackageToolView,
  AgentPackageView,
} from '@/stores/agent'
import type { I18nKey, Locale } from '@/i18n'

export type NaiveTagType = 'default' | 'success' | 'warning' | 'error' | 'info'
type Translate = (key: I18nKey, params?: Record<string, string | number>) => string

export function packageDisplayName(pkg: AgentPackageView, t?: Translate): string {
  return pkg.agent_name || pkg.name || t?.('common.unnamedAgent') || 'Unnamed Agent'
}

export function isPackageReady(instance: AgentPackageInstanceView | null): boolean {
  return instance?.ready === true
}

export function isInstanceInitializing(instance: AgentPackageInstanceView | null): boolean {
  return instance?.status === 'initializing'
}

export function instanceStatusLabel(instance: AgentPackageInstanceView | null, t: Translate): string {
  if (!instance) return t('agentDetail.notInitialized')
  if (instance.error) return t('agentDetail.instanceError')
  if (instance.status === 'initializing') return t('agentDetail.initializing')
  if (instance.ready) {
    return instance.active_request_count
      ? t('agentDetail.runningCount', { count: instance.active_request_count })
      : t('agentDetail.ready')
  }
  return t('agentDetail.notInitialized')
}

export function instanceStatusType(instance: AgentPackageInstanceView | null): NaiveTagType {
  if (instance?.error) return 'error'
  if (instance?.status === 'initializing') return 'info'
  if (instance?.active_request_count) return 'info'
  if (instance?.ready) return 'success'
  return 'default'
}

export function packageInitial(pkg: AgentPackageView): string {
  const name = pkg.agent_name || pkg.name || pkg.package_id
  return name.charAt(0).toUpperCase()
}

export function packageColor(pkg: AgentPackageView): string {
  const colors = ['#18a058', '#2080f0', '#f0a020', '#d03050']
  const hash = pkg.package_id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0)
  return colors[hash % colors.length]
}

export function statusType(status: string): NaiveTagType {
  const types: Record<string, NaiveTagType> = {
    ready: 'success',
    running: 'info',
    failed: 'error',
  }
  return types[status] || 'default'
}

export function formatPackageDate(timestamp: string | null, locale: Locale, t: Translate): string {
  if (!timestamp) return t('common.unknown')
  const date = new Date(timestamp)
  if (isNaN(date.getTime())) return t('common.unknown')
  return date.toLocaleDateString(locale, { month: '2-digit', day: '2-digit' })
}

export function formatPackageDateTime(timestamp: string | null, locale: Locale, t: Translate): string {
  if (!timestamp) return t('common.unknown')
  const date = new Date(timestamp)
  if (isNaN(date.getTime())) return t('common.unknown')
  return date.toLocaleString(locale)
}

export function extensionKey(item: AgentPackageExtensionView): string {
  const payloadId = item.payload?.server_id || item.payload?.skill_id
  return String(payloadId || item.name)
}

export function toolMeta(tool: AgentPackageToolView, t: Translate): string {
  return tool.concurrent === false ? t('agentDetail.serialTool') : t('agentDetail.concurrentTool')
}

export function extensionDescription(item: AgentPackageExtensionView): string {
  return String(item.payload?.description || item.summary || '').trim()
}

export function mcpMeta(server: AgentPackageExtensionView, t: Translate): string {
  const payload = server.payload || {}
  const envCount = Array.isArray(payload.env_keys) ? payload.env_keys.length : 0
  const parts = [
    server.transport || payload.transport,
    server.scope,
    envCount > 0 ? t('agentDetail.envCount', { count: envCount }) : null,
    payload.timeout_seconds ? t('agentDetail.timeoutSeconds', { count: Number(payload.timeout_seconds) }) : null,
  ].filter(Boolean)
  return parts.join(' · ') || t('agentDetail.mcpServer')
}

export function skillMeta(skill: AgentPackageExtensionView, t: Translate): string {
  const payload = skill.payload || {}
  const resourceCount = Number(payload.resource_count || 0)
  const scriptCount = Number(payload.script_count || 0)
  const parts = [
    skill.scope,
    resourceCount > 0 ? t('agentDetail.resourceCount', { count: resourceCount }) : null,
    scriptCount > 0 ? t('agentDetail.scriptCount', { count: scriptCount }) : null,
  ].filter(Boolean)
  return parts.join(' · ') || 'Skill'
}

export function knowledgeMeta(source: AgentPackageKnowledgeSourceView, locale: Locale, t: Translate): string {
  const parts = [
    source.kind,
    source.mode,
    source.document_count != null ? t('knowledge.documents', { count: source.document_count }) : null,
    source.updated_at ? t('agentDetail.updatedAtPrefix', { time: formatPackageDateTime(source.updated_at, locale, t) }) : null,
  ].filter(Boolean)
  return parts.join(' · ') || t('agentDetail.knowledgeSource')
}

export function knowledgeSamples(source: AgentPackageKnowledgeSourceView, t: Translate): string {
  const titles = (source.sample_titles || []).filter(Boolean).slice(0, 3)
  return titles.length > 0 ? t('agentDetail.samples', { titles: titles.join('、') }) : ''
}
