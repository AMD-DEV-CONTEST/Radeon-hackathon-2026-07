export const SYSTEM_CHAT_PACKAGE_ID = 'factory_chat'

export function normalizeResourcePackageId(value: unknown): string | null {
  const normalized = String(value || '').trim()
  if (!normalized || normalized === SYSTEM_CHAT_PACKAGE_ID) return null
  return normalized
}
