import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type ThemeMode = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

interface ThemeContextValue {
  themeMode: ThemeMode
  resolvedTheme: ResolvedTheme
  setThemeMode: (mode: ThemeMode) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function getSystemTheme(): ResolvedTheme {
  if (typeof window === 'undefined') return 'dark'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

interface ThemeProviderProps {
  children: ReactNode
  defaultMode?: ThemeMode
}

export function ThemeProvider({ children, defaultMode = 'system' }: ThemeProviderProps) {
  const [themeMode, setThemeMode] = useState<ThemeMode>(defaultMode)
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() => {
    if (defaultMode === 'system') {
      return getSystemTheme()
    }
    return defaultMode
  })

  useEffect(() => {
    const updateResolvedTheme = () => {
      if (themeMode === 'system') {
        setResolvedTheme(getSystemTheme())
      } else {
        setResolvedTheme(themeMode)
      }
    }

    updateResolvedTheme()

    if (themeMode === 'system') {
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
      const handleChange = () => {
        setResolvedTheme(getSystemTheme())
      }

      mediaQuery.addEventListener('change', handleChange)
      return () => mediaQuery.removeEventListener('change', handleChange)
    }
  }, [themeMode])

  useEffect(() => {
    const root = document.documentElement
    root.classList.remove('light', 'dark')
    root.classList.add(resolvedTheme)

    root.setAttribute('data-theme', resolvedTheme)
  }, [resolvedTheme])

  return (
    <ThemeContext.Provider value={{ themeMode, resolvedTheme, setThemeMode }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}

export function useResolvedTheme(): ResolvedTheme {
  const { resolvedTheme } = useTheme()
  return resolvedTheme
}
