import { useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/authContext'

/**
 * Returns a wrapper that gates an action behind authentication.
 * If the user has no token the browser navigates to /login with a
 * redirect back to the current page; otherwise the action runs.
 */
export function useRequireAuthAction() {
  const { token } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  return useCallback(
    (action: () => void) => {
      if (!token) {
        navigate(`/login?redirect=${encodeURIComponent(location.pathname + location.search)}`)
        return
      }
      action()
    },
    [token, navigate, location],
  )
}
