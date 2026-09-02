// @vitest-environment node
import { describe, it, expect } from 'vitest'
import TestRenderer, { act } from 'react-test-renderer'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { RequireAuth } from './RequireAuth'
import { AuthContext, type AuthContextValue } from './AuthContext'
import { ApiClient } from '../api/client'

function makeValue(over: Partial<AuthContextValue>): AuthContextValue {
  const client = new ApiClient({ fetchImpl: (async () => new Response('{}')) as typeof fetch })
  return {
    client,
    user: null,
    token: null,
    isAuthenticated: false,
    loading: false,
    login: async () => {},
    logout: () => {},
    ...over,
  }
}

function renderGuard(value: AuthContextValue, initialPath = '/') {
  const router = createMemoryRouter(
    [
      { path: '/login', element: <div data-testid="login-page">Sign in</div> },
      {
        path: '*',
        element: (
          <AuthContext.Provider value={value}>
            <RequireAuth>
              <div data-testid="protected">secret content</div>
            </RequireAuth>
          </AuthContext.Provider>
        ),
      },
    ],
    { initialEntries: [initialPath] },
  )
  let root!: TestRenderer.ReactTestRenderer
  act(() => {
    root = TestRenderer.create(<RouterProvider router={router} />)
  })
  return root
}

describe('RequireAuth', () => {
  it('redirects an unauthenticated user to /login', () => {
    const root = renderGuard(makeValue({ isAuthenticated: false, loading: false }))
    const login = root.root.findAllByProps({ 'data-testid': 'login-page' })
    const protectedNodes = root.root.findAllByProps({ 'data-testid': 'protected' })
    expect(login.length).toBe(1)
    expect(protectedNodes.length).toBe(0)
  })

  it('shows a loading state while the session is being restored', () => {
    const root = renderGuard(makeValue({ loading: true }))
    const loading = root.root.findAllByProps({ role: 'status' })
    expect(loading.length).toBeGreaterThan(0)
    expect(root.root.findAllByProps({ 'data-testid': 'protected' }).length).toBe(0)
  })

  it('renders protected content for an authenticated user', () => {
    const root = renderGuard(
      makeValue({
        isAuthenticated: true,
        loading: false,
        user: {
          user_id: 'u1',
          username: 'demo',
          display_name: 'Demo',
          is_active: true,
          is_system_admin: false,
        },
      }),
    )
    expect(root.root.findAllByProps({ 'data-testid': 'protected' }).length).toBe(1)
  })
})
