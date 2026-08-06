import { ChevronDown, Languages } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { LOCALE_OPTIONS } from '../../i18n/locales'
import { useLocaleStore } from '../../i18n/store'
import { cn } from '../../lib/utils'

/** Compact language menu — short label only, does not crowd the navbar. */
export function LanguageSwitcher({ className }: { className?: string }) {
  const locale = useLocaleStore((s) => s.locale)
  const setLocale = useLocaleStore((s) => s.setLocale)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const current = LOCALE_OPTIONS.find((l) => l.id === locale) ?? LOCALE_OPTIONS[0]

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={ref} className={cn('relative', className)}>
      <button
        type="button"
        aria-label="Language"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-8 items-center gap-1 rounded-full border border-white/10 bg-white/[0.03] px-2 text-[11px] font-medium text-slate-300 transition-colors hover:border-[var(--ember)]/40 hover:text-[var(--paper)]"
      >
        <Languages className="h-3.5 w-3.5 opacity-70" />
        <span className="min-w-[1.1rem] text-center">{current.short}</span>
        <ChevronDown className={cn('h-3 w-3 opacity-50 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <ul
          role="listbox"
          className="absolute right-0 top-full z-50 mt-1 min-w-[7.5rem] overflow-hidden rounded-xl border border-white/10 bg-[hsl(var(--popover))] p-1 shadow-xl"
        >
          {LOCALE_OPTIONS.map((opt) => (
            <li key={opt.id}>
              <button
                type="button"
                role="option"
                aria-selected={opt.id === locale}
                onClick={() => {
                  setLocale(opt.id)
                  setOpen(false)
                }}
                className={cn(
                  'flex w-full items-center justify-between gap-3 rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors',
                  opt.id === locale
                    ? 'bg-[hsl(var(--primary))]/12 text-[hsl(var(--primary))]'
                    : 'text-[hsl(var(--popover-foreground))] hover:bg-[hsl(var(--muted))]',
                )}
              >
                <span>{opt.label}</span>
                <span className="text-[10px] opacity-50">{opt.short}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
