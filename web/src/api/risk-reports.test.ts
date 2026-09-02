// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { ApiClient } from './client'

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function clientFor(body: unknown) {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  const client = new ApiClient({ getToken: () => 'token', fetchImpl: (async (url: string, init?: RequestInit) => {
    calls.push({ url, init }); return response(body)
  }) as typeof fetch })
  return { client, calls }
}

describe('UI-3 risk and report API client', () => {
  it('lists risks using project-scoped filters', async () => {
    const { client, calls } = clientFor([])
    await client.listRisks('demo', 'high', 'active')
    expect(calls[0].url).toBe('/projects/demo/risks?severity=high&lifecycle=active')
  })

  it('assigns and transitions risks through the protected routes', async () => {
    const { client, calls } = clientFor({})
    await client.assignRisk('demo', 'risk-1', { risk_id: 'risk-1', assignee_user_id: 'u-member' })
    await client.updateRiskLifecycle('demo', 'risk-1', { action: 'resolve', note: 'mitigated' })
    expect(calls[0].url).toBe('/projects/demo/risks/risk-1/assign')
    expect(calls[0].init?.method).toBe('PUT')
    expect(JSON.parse(String(calls[1].init?.body))).toEqual({ action: 'resolve', note: 'mitigated' })
  })

  it('creates, submits, and approves report drafts through separate endpoints', async () => {
    const { client, calls } = clientFor({ id: 'r-1', project_id: 'demo', title: 'Weekly', content_md: '', version: 1, status: 'draft', author_id: 'u', author_name: 'u', created_at: '', updated_at: '' })
    await client.createReportDraft('demo', { title: 'Weekly', content_md: '# Weekly' })
    await client.submitReport('demo', 'r-1')
    await client.decideReport('demo', 'r-1', { decision: 'approved', comment: 'Reviewed' })
    expect(calls.map((call) => call.url)).toEqual([
      '/projects/demo/reports', '/projects/demo/reports/r-1/submit', '/projects/demo/reports/r-1/approve',
    ])
    expect(JSON.parse(String(calls[2].init?.body))).toEqual({ decision: 'approved', comment: 'Reviewed' })
  })

  it('loads project-scoped discussions', async () => {
    const { client, calls } = clientFor([])
    await client.listComments('demo', 'risk', 'risk-1')
    expect(calls[0].url).toBe('/projects/demo/comments?entity_type=risk&entity_id=risk-1')
  })
})
