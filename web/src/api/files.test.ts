// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { ApiClient } from './client'

describe('ApiClient project-file operations', () => {
  it('sends multipart uploads with a Bearer token and no forced JSON content type', async () => {
    let captured: RequestInit | undefined
    const client = new ApiClient({
      getToken: () => 'token',
      fetchImpl: (async (_url: string, init?: RequestInit) => {
        captured = init
        return new Response(JSON.stringify({
          relative_path: 'source/brief.md', size_bytes: 5, sha256: 'abc', mime_detected: 'text/plain', extension_matched: true, virus_scan_status: 'skipped',
        }), { status: 201, headers: { 'Content-Type': 'application/json' } })
      }) as typeof fetch,
    })
    await client.uploadProjectFile('demo-project', new File(['brief'], 'brief.md', { type: 'text/markdown' }))
    const headers = captured?.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer token')
    expect(headers['Content-Type']).toBeUndefined()
    expect(captured?.body).toBeInstanceOf(FormData)
  })

  it('uses the controlled download endpoint without the source prefix', async () => {
    let url = ''
    const client = new ApiClient({
      getToken: () => 'token',
      fetchImpl: (async (input: string) => {
        url = input
        return new Response('content', { status: 200, headers: { 'content-disposition': 'attachment; filename="brief.md"' } })
      }) as typeof fetch,
    })
    await client.downloadProjectFile('demo-project', 'source/brief.md')
    expect(url).toBe('/api/projects/demo-project/files/download/brief.md')
  })
})
