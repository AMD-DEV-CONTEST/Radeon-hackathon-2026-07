// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { ApiClient } from './client'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('controlled integration and operations client', () => {
  it('keeps preview and confirmed SCM execution as separate endpoints', async () => {
    const calls: Array<{ url: string; body: string }> = []
    const client = new ApiClient({ fetchImpl: (async (url, init) => {
      calls.push({ url: String(url), body: String(init?.body ?? '') })
      return jsonResponse({ ok: true, preview: {}, confirmation_id: 'once' })
    }) as typeof fetch })
    const change = { project_id: 'demo', target: 'github_issues' as const, operation: 'create' as const, items: [{ title: 'Review release' }] }
    await client.previewScmChange(change)
    await client.executeScmChange(change, 'once')
    expect(calls.map((item) => item.url)).toEqual(['/api/integrations/scm/preview', '/api/integrations/scm/execute'])
    expect(JSON.parse(calls[1].body)).toMatchObject({ ...change, confirmation_id: 'once' })
  })

  it('uses the server-protected operations endpoints', async () => {
    const calls: string[] = []
    const client = new ApiClient({ fetchImpl: (async (url) => {
      calls.push(String(url)); return jsonResponse({})
    }) as typeof fetch })
    await client.getAdminHealth(); await client.getAdminQueue(); await client.getAdminCache(); await client.listBackups()
    expect(calls).toEqual(['/monitor/health', '/monitor/queue', '/monitor/cache', '/admin/backup'])
  })
})
