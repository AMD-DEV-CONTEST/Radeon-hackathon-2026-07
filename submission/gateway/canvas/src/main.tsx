import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { LoginPage, loadToken, storeToken, clearToken } from './LoginPage.tsx'

function Root() {
  const [token, setToken] = useState<string | null>(() => loadToken())

  if (!token) {
    return <LoginPage onLogin={(t) => { storeToken(t); setToken(t) }} />
  }

  return <App gatewayToken={token} onAuthError={() => { clearToken(); setToken(null) }} />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
