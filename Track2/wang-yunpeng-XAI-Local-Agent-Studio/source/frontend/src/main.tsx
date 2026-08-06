import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { ThemeProvider } from './theme-context'
import './index.css'
import './liquid-glass.css'
import './theme.css'
import './effects.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode><ThemeProvider defaultMode="system"><App /></ThemeProvider></StrictMode>,
)
