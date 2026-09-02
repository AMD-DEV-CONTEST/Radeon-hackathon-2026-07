// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { ApiClient } from './client'
import { ApiError, NETWORK_ERROR_STATUS } from './errors'
import type { TokenResponse } from './dto'

interface Captured {
  url: string
  method: string
  headers: Record<string, string>
  body?: string
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** A fetch that records the request and replies from a per-path handler. */
function recordingFetch(handler: (req: Captured) => Response) {
  return (async (input: RequestInfo | URL, init?: RequestInit) => {
    const captured: Captured = {
      url: typeof input === 'string' ? input : input.toString(),
      method: (init?.method ?? 'GET').toUpperCase(),
      headers: (init?.headers as Record<string, string>) ?? {},
      body: init?.body as string | undefined,
    }
    return handler(captured)
  }) as typeof fetch
}

const OK_TOKEN: TokenResponse = {
  access_token: 'tok-123',
  token_type: 'bearer',
  user_id: 'u1',
  username: 'demo',
  display_name: 'Demo',
  is_system_admin: false,
}

describe('ApiClient.request', () => {
  it('prepends baseUrl to the request path', async () => {
    let seen = ''
    const client = new ApiClient({
      baseUrl: 'https://api.example.com/',
      fetchImpl: recordingFetch((req) => {
        seen = req.url
        return jsonResponse(200, OK_TOKEN)
      }),
    })
    await client.login({ username: 'a', password: 'b' })
    expect(seen).toBe('https://api.example.com/auth/login')
  })

  it('attaches a Bearer token from getToken', async () => {
    let authHeader = ''
    const client = new ApiClient({
      getToken: () => 'secret-token',
      fetchImpl: recordingFetch((req) => {
        authHeader = req.headers['Authorization'] ?? ''
        return jsonResponse(200, OK_TOKEN)
      }),
    })
    await client.getMe()
    expect(authHeader).toBe('Bearer secret-token')
  })

  it('sends the JSON body for POST', async () => {
    let body = ''
    const client = new ApiClient({
      fetchImpl: recordingFetch((req) => {
        body = req.body ?? ''
        return jsonResponse(200, OK_TOKEN)
      }),
    })
    await client.login({ username: 'alice', password: 'pw' })
    expect(JSON.parse(body)).toEqual({ username: 'alice', password: 'pw' })
  })

  it('creates a project through the authenticated projects endpoint', async () => {
    let seen: Captured | undefined
    const client = new ApiClient({
      getToken: () => 'tok-123',
      fetchImpl: recordingFetch((request) => {
        seen = request
        return jsonResponse(201, { project_id: 'release-demo', name: 'Release demo', description: null, created_at: '', status: 'created', source_file_count: 0, failed_file_count: 0 })
      }),
    })
    await client.createProject({ project_id: 'release-demo', name: 'Release demo', description: null })
    expect(seen?.url).toBe('/api/projects')
    expect(seen?.method).toBe('POST')
    expect(JSON.parse(seen?.body ?? '{}')).toMatchObject({ project_id: 'release-demo' })
  })
})

describe('ApiClient error mapping', () => {
  const cases: Array<[number, object]> = [
    [401, { error_code: 'AUTH_EXPIRED', message: 'expired', user_message: 'Session expired' }],
    [403, { error_code: 'FORBIDDEN', user_message: 'No permission' }],
    [404, { error_code: 'NOT_FOUND', user_message: 'Not found' }],
    [409, { error_code: 'CONFLICT', user_message: 'Conflict' }],
    [500, { error_code: 'SERVER', user_message: 'Server error' }],
  ]

  for (const [status, body] of cases) {
    it(`maps HTTP ${status} to an ApiError with the user_message`, async () => {
      const client = new ApiClient({
        fetchImpl: recordingFetch(() => jsonResponse(status, body)),
      })
      await expect(client.getMe()).rejects.toBeInstanceOf(ApiError)
      try {
        await client.getMe()
      } catch (e) {
        const err = e as ApiError
        expect(err.status).toBe(status)
        expect(err.userMessage).toBe((body as { user_message: string }).user_message)
      }
    })
  }

  it('parses a FastAPI 422 validation body into a readable message', async () => {
    const client = new ApiClient({
      fetchImpl: recordingFetch(() =>
        jsonResponse(422, {
          detail: [
            { loc: ['body', 'username'], msg: 'field required', type: 'value_error' },
          ],
        }),
      ),
    })
    try {
      await client.getMe()
      throw new Error('should have thrown')
    } catch (e) {
      const err = e as ApiError
      expect(err.status).toBe(422)
      expect(err.message).toContain('username')
      expect(err.errorCode).toBe('VALIDATION_ERROR')
    }
  })

  it('surfaces a network failure as a status-0 ApiError', async () => {
    const client = new ApiClient({
      fetchImpl: (async () => {
        throw new Error('offline')
      }) as typeof fetch,
    })
    try {
      await client.getMe()
      throw new Error('should have thrown')
    } catch (e) {
      const err = e as ApiError
      expect(err.status).toBe(NETWORK_ERROR_STATUS)
      expect(err.isNetworkError).toBe(true)
    }
  })

  it('maps an abort/timeout to a network ApiError', async () => {
    const client = new ApiClient({
      timeoutMs: 5,
      fetchImpl: ((_url: string, init?: RequestInit) => {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () =>
            reject(new DOMException('Aborted', 'AbortError')),
          )
        })
      }) as typeof fetch,
    })
    try {
      await client.getMe()
      throw new Error('should have thrown')
    } catch (e) {
      const err = e as ApiError
      expect(err.isNetworkError).toBe(true)
    }
  })
})
