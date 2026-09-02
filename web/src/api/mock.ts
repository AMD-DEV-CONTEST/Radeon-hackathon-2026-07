// Mock data and a mock `fetch` for OFFLINE REGRESSION and automated tests only.
//
// CONTRACT RULE (UI-0 / spec): mock data must NEVER be used to fake that the
// model has actually run. In the running application the real `ApiClient`
// always talks to the backend; this module is referenced only by the test
// suite and is clearly labelled as mock (note the `mock-` prefixed ids).

import type {
  UserProfile,
  Project,
  ProjectOverview,
  TokenResponse,
} from './dto'

export const MOCK_TOKEN: TokenResponse = {
  access_token: 'mock-access-token',
  token_type: 'bearer',
  user_id: 'mock-user-1',
  username: 'demo',
  display_name: 'Demo User',
  is_system_admin: false,
}

export const MOCK_USER: UserProfile = {
  user_id: 'mock-user-1',
  username: 'demo',
  display_name: 'Demo User',
  is_active: true,
  is_system_admin: false,
}

export const MOCK_PROJECTS: Project[] = [
  {
    project_id: 'demo-proj',
    name: 'Demo Project',
    description: 'Mock project used for offline UI regression.',
    created_at: '2026-07-23T00:00:00Z',
    status: 'ready',
    source_file_count: 12,
    failed_file_count: 0,
  },
]

export const MOCK_OVERVIEW: ProjectOverview = {
  project_id: 'demo-proj',
  project_name: 'Demo Project',
  task_stats: { total: 4, not_started: 2, in_progress: 1, completed: 1 },
  risk_stats: { total_active: 3, high: 2, medium: 1 },
  pending_confirmations: 1,
  recent_doc_changes: [
    {
      path: 'requirements.md',
      sha256: 'mock-sha256',
      is_current: true,
      last_seen: '2026-07-23T09:00:00Z',
    },
  ],
  recent_runs: [
    // Clearly mock: the `mock-` prefix signals this is NOT a real model run.
    {
      run_id: 'mock-run-1',
      status: 'completed',
      created_at: '2026-07-23T08:30:00Z',
      completed_at: '2026-07-23T08:31:00Z',
    },
  ],
}

export interface MockFetchRule {
  method?: string
  path: string
  status?: number
  body?: unknown
}

/**
 * Build a `fetch` implementation backed by explicit rules. Unmatched requests
 * resolve to a 404 so tests fail loudly instead of silently passing.
 */
export function createMockFetch(rules: MockFetchRule[]): typeof fetch {
  return (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const method = (init?.method ?? 'GET').toUpperCase()
    const rule = rules.find(
      (r) => (r.method ?? 'GET') === method && url.endsWith(r.path),
    )
    const status = rule?.status ?? 404
    const body = rule?.body ?? { detail: 'not found' }
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  }) as typeof fetch
}
