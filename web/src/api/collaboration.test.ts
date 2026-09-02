// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { ApiClient } from './client'

function capture() {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  const client = new ApiClient({ getToken: () => 'token', fetchImpl: (async (url: string, init?: RequestInit) => {
    calls.push({ url, init }); return new Response(JSON.stringify({}), { headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch })
  return { client, calls }
}

describe('UI-4 collaboration client', () => {
  it('uses project-scoped member management paths', async () => {
    const { client, calls } = capture()
    await client.addMember('demo', { user_id: 'u-member', role: 'member' })
    await client.updateMemberRole('demo', 'u-member', { user_id: 'u-member', role: 'pm' })
    await client.removeMember('demo', 'u-member')
    expect(calls.map((call) => [call.url, call.init?.method])).toEqual([
      ['/projects/demo/members', 'POST'], ['/projects/demo/members/u-member', 'PUT'], ['/projects/demo/members/u-member', 'DELETE'],
    ])
  })

  it('queries and marks notifications through the current-user inbox API', async () => {
    const { client, calls } = capture()
    await client.listNotifications(true, 20)
    await client.markNotificationRead('n-1')
    await client.markAllNotificationsRead()
    expect(calls.map((call) => [call.url, call.init?.method])).toEqual([
      ['/notifications?unread_only=true&limit=20', 'GET'], ['/notifications/n-1/read', 'PUT'], ['/notifications/read-all', 'PUT'],
    ])
  })
})
