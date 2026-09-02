// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { ApiClient } from './client'

function response(body: unknown, status = 200, headers?: Record<string, string>): Response {
  return new Response(body instanceof Blob ? body : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

function runState(run_id = 'run-1') {
  return {
    run_id, project_id: 'demo-project', status: 'queued', current_step: 0,
    created_at: '2026-07-24T00:00:00Z', updated_at: '2026-07-24T00:00:00Z',
    completed_at: null, error: null, artifacts: {}, timing_by_step: [], retry_count: 0,
    cancel_requested: false, current_file: null, total_steps: 8,
  }
}

describe('ApiClient run operations', () => {
  it('creates then executes a run using authenticated controlled endpoints', async () => {
    const seen: Array<{ url: string; method: string; auth?: string }> = []
    const client = new ApiClient({
      getToken: () => 'token',
      fetchImpl: (async (url: string, init?: RequestInit) => {
        seen.push({ url, method: init?.method ?? 'GET', auth: (init?.headers as Record<string, string>).Authorization })
        return response(runState())
      }) as typeof fetch,
    })
    await client.createRun('demo-project')
    await client.executeRun('demo-project', 'run-1')
    expect(seen).toEqual([
      { url: '/api/projects/demo-project/runs', method: 'POST', auth: 'Bearer token' },
      { url: '/api/projects/demo-project/runs/run-1/execute', method: 'POST', auth: 'Bearer token' },
    ])
  })

  it('downloads an artifact through the authorized API instead of using a file path', async () => {
    let seen: { url: string; auth?: string } | null = null
    const client = new ApiClient({
      getToken: () => 'token',
      fetchImpl: (async (url: string, init?: RequestInit) => {
        seen = { url, auth: (init?.headers as Record<string, string>).Authorization }
        return new Response('report body', {
          status: 200,
          headers: { 'content-disposition': 'attachment; filename="report.md"' },
        })
      }) as typeof fetch,
    })
    const file = await client.downloadRunArtifact('demo-project', 'run-1', 'report')
    expect(seen).toEqual({ url: '/api/projects/demo-project/runs/run-1/artifacts/report', auth: 'Bearer token' })
    expect(file.filename).toBe('report.md')
    expect(await file.blob.text()).toBe('report body')
  })
})
