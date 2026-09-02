// @vitest-environment node
//
// UI-2 task workbench contract tests. Every ApiClient task method is covered:
// URL construction, HTTP verb, payload shape, auth header, multipart handling
// and server-side rejection mapping (the server stays the single authority
// for lifecycle transitions).
import { describe, expect, it } from 'vitest'
import { ApiClient } from './client'
import { ApiError } from './errors'
import {
  TASK_ALLOWED_TRANSITIONS,
  type PhaseFTaskStatus,
  type TaskRecord,
} from './dto'

interface Captured {
  url: string
  init?: RequestInit
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function makeClient(response: () => Response): { client: ApiClient; calls: Captured[] } {
  const calls: Captured[] = []
  const client = new ApiClient({
    getToken: () => 'token',
    fetchImpl: (async (url: string, init?: RequestInit) => {
      calls.push({ url, init })
      return response()
    }) as typeof fetch,
  })
  return { client, calls }
}

const TASK: TaskRecord = {
  id: 't-1', project_id: 'demo-project', title: 'Ship weekly report', owner: 'alice',
  due_date: '2026-07-31', priority: 'P1', acceptance_criteria: 'Report published',
  dependencies: [], source_ref: 'minutes.md#L10', status: 'in_progress',
  confirmed_by: 'bob', confirmed_at: '2026-07-20T10:00:00Z',
  confirmation_basis: 'meeting decision', confirmation_notes: null,
  created_at: '2026-07-19T09:00:00Z', updated_at: '2026-07-21T09:00:00Z',
}

describe('ApiClient task CRUD & lifecycle', () => {
  it('lists tasks without a status query by default', async () => {
    const { client, calls } = makeClient(() => jsonResponse([TASK]))
    const tasks = await client.listTasks('demo-project')
    expect(calls[0].url).toBe('/api/projects/demo-project/tasks')
    expect(calls[0].init?.method).toBe('GET')
    expect(tasks).toHaveLength(1)
  })

  it('appends an encoded status filter when provided', async () => {
    const { client, calls } = makeClient(() => jsonResponse([]))
    await client.listTasks('demo-project', 'in_progress')
    expect(calls[0].url).toBe('/api/projects/demo-project/tasks?status=in_progress')
  })

  it('fetches a single task with a Bearer token', async () => {
    const { client, calls } = makeClient(() => jsonResponse(TASK))
    const task = await client.getTask('demo-project', 't-1')
    expect(calls[0].url).toBe('/api/projects/demo-project/tasks/t-1')
    const headers = calls[0].init?.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer token')
    expect(task.id).toBe('t-1')
  })

  it('creates a task via POST with a JSON body', async () => {
    const { client, calls } = makeClient(() => jsonResponse(TASK, 201))
    await client.createTask('demo-project', {
      title: 'Ship weekly report', owner: 'alice', due_date: null, priority: 'P1',
      acceptance_criteria: '', dependencies: [], source_ref: null, status: 'not_started',
    })
    expect(calls[0].init?.method).toBe('POST')
    const body = JSON.parse(String(calls[0].init?.body))
    expect(body.title).toBe('Ship weekly report')
    expect(body.status).toBe('not_started')
  })

  it('patches task fields via PATCH', async () => {
    const { client, calls } = makeClient(() => jsonResponse(TASK))
    await client.updateTask('demo-project', 't-1', { owner: 'carol', priority: 'P0' })
    expect(calls[0].url).toBe('/api/projects/demo-project/tasks/t-1')
    expect(calls[0].init?.method).toBe('PATCH')
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ owner: 'carol', priority: 'P0' })
  })

  it('requests a transition with status and reason while the server owns the actor', async () => {
    const { client, calls } = makeClient(() => jsonResponse({ ...TASK, status: 'completed' }))
    await client.transitionTask('demo-project', 't-1', {
      status: 'completed', reason: 'all acceptance criteria met',
    })
    expect(calls[0].url).toBe('/api/projects/demo-project/tasks/t-1/transition')
    const body = JSON.parse(String(calls[0].init?.body))
    expect(body).toEqual({
      status: 'completed', reason: 'all acceptance criteria met',
    })
  })

  it('surfaces server transition rejections as ApiError with the backend code', async () => {
    // The tasks router nests the structured error under FastAPI's `detail`.
    const { client } = makeClient(() => jsonResponse({
      detail: {
        error_code: 'TASK_INVALID_TRANSITION',
        message: 'Invalid task status transition.',
        user_message: 'This status change is not allowed.',
      },
    }, 400))
    const attempt = client.transitionTask('demo-project', 't-1', {
      status: 'in_progress', reason: 'reopen',
    })
    await expect(attempt).rejects.toMatchObject({
      name: 'ApiError', status: 400, errorCode: 'TASK_INVALID_TRANSITION',
      message: 'This status change is not allowed.',
    })
  })

  it('also accepts flat structured error bodies (non-nested routers)', async () => {
    const { client } = makeClient(() => jsonResponse({
      error_code: 'TASK_CANCELLED_FINAL', message: 'final', user_message: 'Cancelled is final.',
    }, 400))
    await expect(client.transitionTask('demo-project', 't-1', {
      status: 'in_progress', reason: 'reopen',
    })).rejects.toMatchObject({ errorCode: 'TASK_CANCELLED_FINAL' })
  })

  it('maps 404 bodies to ApiError for unknown tasks', async () => {
    const { client } = makeClient(() => jsonResponse({
      detail: { error_code: 'TASK_NOT_FOUND', message: 'missing', user_message: 'Task not found.' },
    }, 404))
    await expect(client.getTask('demo-project', 'nope')).rejects.toBeInstanceOf(ApiError)
  })

  it('loads the per-task change history', async () => {
    const { client, calls } = makeClient(() => jsonResponse([{
      id: 1, task_id: 't-1', project_id: 'demo-project', from_status: 'not_started',
      to_status: 'in_progress', changed_by: 'alice', change_reason: 'kick-off',
      changed_at: '2026-07-20T08:00:00Z',
    }]))
    const history = await client.getTaskHistory('demo-project', 't-1')
    expect(calls[0].url).toBe('/api/projects/demo-project/tasks/t-1/history')
    expect(history[0].to_status).toBe('in_progress')
  })
})

describe('ApiClient confirmation queue', () => {
  it('lists the queue filtered to pending items', async () => {
    const { client, calls } = makeClient(() => jsonResponse([]))
    await client.listConfirmationQueue('demo-project', 'pending')
    expect(calls[0].url).toBe(
      '/api/projects/demo-project/tasks/confirmation-queue?status=pending',
    )
  })

  it('records an accept decision with basis while the server owns the operator', async () => {
    const { client, calls } = makeClient(() => jsonResponse({
      id: 7, task_id: 't-9', project_id: 'demo-project', candidate_title: 'Draft plan',
      candidate_owner: null, candidate_due_date: null, candidate_priority: null,
      candidate_acceptance: null, candidate_dependencies: [], source_ref: null,
      source_kind: 'meeting_minutes', confidence: 0.8, status: 'accepted',
      confirmed_by: 'alice', confirmation_basis: 'agreed in weekly sync',
      confirmation_notes: null, confirmed_at: '2026-07-24T10:00:00Z',
      created_at: '2026-07-23T10:00:00Z',
    }))
    await client.processConfirmation('demo-project', 't-9', {
      action: 'accept', confirmation_basis: 'agreed in weekly sync',
    })
    expect(calls[0].url).toBe('/api/projects/demo-project/tasks/confirmation/t-9')
    const body = JSON.parse(String(calls[0].init?.body))
    expect(body.action).toBe('accept')
    expect(body.confirmed_by).toBeUndefined()
  })

  it('sends modified fields when the decision is modify', async () => {
    const { client, calls } = makeClient(() => jsonResponse({}, 200))
    await client.processConfirmation('demo-project', 't-9', {
      action: 'modify', modified_title: 'Draft Q3 plan',
      modified_owner: 'bob', modified_due_date: '2026-08-01', modified_priority: 'P2',
    })
    const body = JSON.parse(String(calls[0].init?.body))
    expect(body.action).toBe('modify')
    expect(body.modified_title).toBe('Draft Q3 plan')
    expect(body.modified_due_date).toBe('2026-08-01')
  })

  it('propagates CONFIRMATION_ALREADY_PROCESSED errors', async () => {
    const { client } = makeClient(() => jsonResponse({
      detail: {
        error_code: 'CONFIRMATION_ALREADY_PROCESSED', message: 'done',
        user_message: 'Already processed.',
      },
    }, 400))
    await expect(client.processConfirmation('demo-project', 't-9', {
      action: 'ignore',
    })).rejects.toMatchObject({ errorCode: 'CONFIRMATION_ALREADY_PROCESSED' })
  })
})

describe('ApiClient extraction & audit log', () => {
  it('submits source text for candidate extraction', async () => {
    const { client, calls } = makeClient(() => jsonResponse({ candidates: [] }))
    await client.extractTasks('demo-project', {
      source_text: 'Weekly sync notes', source_kind: 'meeting_minutes',
      project_id: 'demo-project',
    })
    expect(calls[0].url).toBe('/api/projects/demo-project/tasks/extract')
    expect(JSON.parse(String(calls[0].init?.body)).source_kind).toBe('meeting_minutes')
  })

  it('submits candidates into the confirmation queue', async () => {
    const { client, calls } = makeClient(() => jsonResponse([], 201))
    await client.submitCandidates('demo-project', {
      candidates: [{
        title: 'Draft plan', owner: null, due_date: null, priority: null,
        acceptance_criteria: null, dependencies: [], source_ref: null,
        source_kind: 'meeting_minutes', confidence: 0.7,
      }],
    })
    expect(calls[0].url).toBe('/api/projects/demo-project/tasks/submit-candidates')
    expect(calls[0].init?.method).toBe('POST')
  })

  it('fetches the audit log with an explicit limit', async () => {
    const { client, calls } = makeClient(() => jsonResponse([]))
    await client.getTaskAuditLog('demo-project', 50)
    expect(calls[0].url).toBe('/api/projects/demo-project/tasks/audit-log?limit=50')
  })

  it('defaults the audit log limit to 100', async () => {
    const { client, calls } = makeClient(() => jsonResponse([]))
    await client.getTaskAuditLog('demo-project')
    expect(calls[0].url).toBe('/api/projects/demo-project/tasks/audit-log?limit=100')
  })
})

describe('ApiClient task import (multipart)', () => {
  it('previews an import as multipart without forcing a JSON content type', async () => {
    const { client, calls } = makeClient(() => jsonResponse({
      new_rows: 2, duplicate_rows: 1, conflict_rows: 0,
      preview: [{ title: 'A', status: 'new' }],
    }))
    const diff = await client.previewTaskImport(
      'demo-project', new File(['title\nA'], 'tasks.csv', { type: 'text/csv' }),
    )
    expect(calls[0].url).toBe('/api/projects/demo-project/tasks/import-preview')
    const headers = calls[0].init?.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer token')
    expect(headers['Content-Type']).toBeUndefined()
    expect(calls[0].init?.body).toBeInstanceOf(FormData)
    expect(diff.new_rows).toBe(2)
  })

  it('confirms an import with flags while the server owns operator identity', async () => {
    const { client, calls } = makeClient(() => jsonResponse({
      imported: 2, skipped: 1, errors: 0, details: [],
    }, 201))
    await client.confirmTaskImport(
      'demo-project', new File(['title\nA'], 'tasks.csv', { type: 'text/csv' }),
      false, true,
    )
    expect(calls[0].url).toBe('/api/projects/demo-project/tasks/import-confirm')
    const form = calls[0].init?.body as FormData
    expect(form.get('confirmed_by')).toBeNull()
    expect(form.get('skip_duplicates')).toBe('false')
    expect(form.get('overwrite_conflicts')).toBe('true')
    expect(form.get('file')).toBeInstanceOf(File)
  })

  it('maps unsupported-format rejections to ApiError', async () => {
    const { client } = makeClient(() => jsonResponse({
      detail: {
        error_code: 'IMPORT_FILE_UNSUPPORTED', message: 'bad ext',
        user_message: 'Only CSV/XLSX files are supported.',
      },
    }, 400))
    await expect(client.previewTaskImport(
      'demo-project', new File(['x'], 'tasks.txt', { type: 'text/plain' }),
    )).rejects.toMatchObject({ errorCode: 'IMPORT_FILE_UNSUPPORTED' })
  })
})

describe('task lifecycle mirror (TASK_ALLOWED_TRANSITIONS)', () => {
  const STATUSES: PhaseFTaskStatus[] = [
    'pending_confirmation', 'not_started', 'in_progress', 'mostly_completed',
    'completed', 'delayed', 'cancelled',
  ]

  it('covers every status exactly once', () => {
    expect(Object.keys(TASK_ALLOWED_TRANSITIONS).sort()).toEqual([...STATUSES].sort())
  })

  it('marks completed and cancelled as final states', () => {
    expect(TASK_ALLOWED_TRANSITIONS.completed).toEqual([])
    expect(TASK_ALLOWED_TRANSITIONS.cancelled).toEqual([])
  })

  it('only references known statuses and never self-loops', () => {
    for (const [from, targets] of Object.entries(TASK_ALLOWED_TRANSITIONS)) {
      for (const target of targets) {
        expect(STATUSES).toContain(target)
        expect(target).not.toBe(from)
      }
    }
  })

  it('matches the backend graph edge-for-edge', () => {
    // Mirror of app/schemas/task_sql.py::ALLOWED_TRANSITIONS — additionally
    // pinned by scripts/validate_task_ui.py against the backend source.
    expect(TASK_ALLOWED_TRANSITIONS).toEqual({
      pending_confirmation: ['not_started', 'cancelled'],
      not_started: ['in_progress', 'cancelled', 'delayed'],
      in_progress: ['mostly_completed', 'completed', 'delayed', 'cancelled'],
      mostly_completed: ['completed', 'in_progress', 'delayed'],
      completed: [],
      delayed: ['in_progress', 'completed', 'cancelled'],
      cancelled: [],
    })
  })
})
