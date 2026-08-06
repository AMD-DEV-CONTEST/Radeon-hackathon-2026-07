import { motion } from 'framer-motion'
import { useTheme, type ThemeMode } from './theme-context'

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-4 h-4">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  )
}
function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
}
function MonitorIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </svg>
  )
}

export function ThemeToggle() {
  const { themeMode, setThemeMode } = useTheme()

  const handleThemeToggle = () => {
    const modes: ThemeMode[] = ['light', 'dark', 'system']
    const currentIndex = modes.indexOf(themeMode)
    const nextMode = modes[(currentIndex + 1) % modes.length]
    setThemeMode(nextMode)
  }

  const Icon = themeMode === 'system' ? MonitorIcon : themeMode === 'dark' ? MoonIcon : SunIcon
  const themeLabel = themeMode === 'system' ? '跟随系统' : themeMode === 'dark' ? '深色' : '浅色'

  return (
    <motion.button
      onClick={handleThemeToggle}
      className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] transition-all duration-200"
      style={{ transformPerspective: 600 }}
      whileHover={{ scale: 1.04, rotateX: 8, rotateY: -8 }}
      whileTap={{ scale: 0.95, rotateX: 0, rotateY: 0 }}
      title={`主题: ${themeLabel}`}
    >
      <Icon />
    </motion.button>
  )
}
