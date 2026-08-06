import type { LocalModelProfile } from '@/api/modelPool'

export interface ModelProfileOption {
  label: string
  value: string
}

export function enabledChatProfiles(profiles: LocalModelProfile[]): LocalModelProfile[] {
  return profiles.filter(profile => (
    profile.kind === 'chat'
    && profile.enabled
    && profile.artifact?.enabled !== false
  ))
}

export function runtimeMainModelOptions(
  profiles: LocalModelProfile[],
  defaultProfileId: string | null | undefined,
  defaultLabel: string,
): ModelProfileOption[] {
  const enabledProfiles = enabledChatProfiles(profiles)
  const defaultProfile = enabledProfiles.find(profile => profile.profile_id === defaultProfileId)
  const resolvedDefaultLabel = defaultProfile
    ? `${defaultLabel} · ${profileDisplayName(defaultProfile)}`
    : defaultLabel
  return [
    { label: resolvedDefaultLabel, value: '' },
    ...enabledProfiles.map(profile => ({
      label: profileDisplayName(profile),
      value: profile.profile_id,
    })),
  ]
}

function profileDisplayName(profile: LocalModelProfile): string {
  return profile.display_name || profile.served_model_name || profile.profile_id
}
