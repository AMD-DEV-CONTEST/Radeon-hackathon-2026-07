import React, { createContext, useContext, useState, useCallback, type ReactNode } from 'react'
import type { AuthState, Role, DocumentRecord, SelfTestResponse } from '@/types'
import { setToken } from '@/lib/api'
import { now } from '@/lib/utils'

interface AppContextValue {
  auth: AuthState | null
  login: (token: string, role: Role, expiresAt: number) => void
  logout: () => void
  documents: DocumentRecord[]
  addDocument: (doc: DocumentRecord) => void
  updateDocument: (id: string, updates: Partial<DocumentRecord>) => void
  selectedDocumentId: string | null
  setSelectedDocumentId: (id: string | null) => void
  currentPage: Page
  setCurrentPage: (page: Page) => void
  selftest: SelfTestResponse | null
  setSelftest: (r: SelfTestResponse | null) => void
}

export type Page = 'overview' | 'documents' | 'audit' | 'activity' | 'security'

const AppContext = createContext<AppContextValue | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState | null>(() => {
    // Try to restore from sessionStorage (not localStorage — security)
    try {
      const s = sessionStorage.getItem('veil_session')
      if (s) {
        const parsed = JSON.parse(s) as AuthState
        if (parsed.expiresAt > now()) {
          setToken(parsed.token)
          return parsed
        }
      }
    } catch { /* ignore */ }
    return null
  })

  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null)
  const [currentPage, setCurrentPage] = useState<Page>('overview')
  const [selftest, setSelftest] = useState<SelfTestResponse | null>(null)

  const login = useCallback((token: string, role: Role, expiresAt: number) => {
    const state: AuthState = { token, role, expiresAt }
    setAuth(state)
    setToken(token)
    try { sessionStorage.setItem('veil_session', JSON.stringify(state)) } catch { /* ignore */ }
  }, [])

  const logout = useCallback(() => {
    setAuth(null)
    setToken(null)
    try { sessionStorage.removeItem('veil_session') } catch { /* ignore */ }
    setDocuments([])
    setSelectedDocumentId(null)
    setCurrentPage('overview')
    setSelftest(null)
  }, [])

  const addDocument = useCallback((doc: DocumentRecord) => {
    setDocuments(prev => [doc, ...prev])
  }, [])

  const updateDocument = useCallback((id: string, updates: Partial<DocumentRecord>) => {
    setDocuments(prev => prev.map(d => d.document_id === id ? { ...d, ...updates } : d))
  }, [])

  return (
    <AppContext.Provider value={{
      auth, login, logout,
      documents, addDocument, updateDocument,
      selectedDocumentId, setSelectedDocumentId,
      currentPage, setCurrentPage,
      selftest, setSelftest,
    }}>
      {children}
    </AppContext.Provider>
  )
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}

export function useAuth() {
  return useApp().auth
}
