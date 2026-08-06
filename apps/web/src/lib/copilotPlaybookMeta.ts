/** Audience labels for Copilot Playbook entries (static map, no DB migration). */
export type PlaybookAudience = 'customer' | 'developer' | 'cloud'

export const PLAYBOOK_AUDIENCE: Record<string, PlaybookAudience[]> = {
  local_agent_unreachable: ['customer', 'developer'],
  python_venv_missing: ['customer'],
  python_dev_missing: ['customer'],
  pip_install_slow: ['customer'],
  github_clone_slow: ['customer'],
  dialout_missing: ['customer'],
  no_cameras: ['customer'],
  camera_busy: ['customer'],
  no_serial: ['customer'],
  robots_api_error: ['customer', 'cloud'],
  cloud_ssl_mismatch: ['customer', 'cloud'],
  database_error: ['cloud'],
  training_auth_required: ['customer', 'cloud'],
  qualia_not_configured: ['cloud'],
  lerobot_missing: ['customer'],
  vite_dev_not_running: ['developer'],
  port_8002_in_use: ['customer', 'developer'],
  llm_provider_disabled: ['cloud'],
  llm_call_failed: ['cloud'],
  cloud_api_unreachable: ['cloud'],
  training_job_failed: ['customer', 'cloud'],
}

export function playbookAudienceLabel(audiences: PlaybookAudience[]): string {
  if (audiences.includes('developer') && !audiences.includes('customer')) {
    return '开发者'
  }
  if (audiences.includes('cloud')) {
    return '云端'
  }
  return '客户'
}

export function filterPlaybooksForContext<T extends { code: string }>(
  matches: T[],
  isDev: boolean,
): T[] {
  return matches.filter((m) => {
    const aud = PLAYBOOK_AUDIENCE[m.code] ?? ['customer']
    if (isDev) return true
    return aud.includes('customer') || aud.includes('cloud')
  })
}
