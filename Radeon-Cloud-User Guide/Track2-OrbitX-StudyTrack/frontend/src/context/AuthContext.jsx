/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { api } from '../api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(() => localStorage.getItem('st_token'))
  const [loading, setLoading] = useState(() => Boolean(localStorage.getItem('st_token')))

  const logout = useCallback(() => {
    localStorage.removeItem('st_token')
    setToken(null)
    setUser(null)
    setLoading(false)
    delete api.defaults.headers.common['Authorization']
  }, [])

  const login = useCallback(async (email, password) => {
    try {
      const res = await api.post('/api/auth/login', { email: email.trim(), password })
      const { access_token, user: u } = res.data
      localStorage.setItem('st_token', access_token)
      setToken(access_token)
      setUser(u)
      setLoading(false)
      return u
    } catch (err) {
      setLoading(false)
      throw err
    }
  }, [])

  const register = useCallback(async (username, email, password, confirm = '') => {
    try {
      const res = await api.post('/api/auth/register', {
        username,
        email: email.trim(),
        password,
        confirm_password: confirm,
      })
      const { access_token, user: u } = res.data
      localStorage.setItem('st_token', access_token)
      setToken(access_token)
      setUser(u)
      setLoading(false)
      return u
    } catch (err) {
      setLoading(false)
      throw err
    }
  }, [])

  useEffect(() => {
    if (!token) return

    api.defaults.headers.common['Authorization'] = `Bearer ${token}`

    api.get('/api/auth/me')
      .then(res => {
        setUser(res.data)
        setLoading(false)
      })
      .catch(() => {
        logout()
      })
  }, [token, logout])

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
