import type { ButtonHTMLAttributes, ReactNode } from "react"
import { cn } from "../../lib/cn"

type Variant = "primary" | "secondary" | "ghost" | "danger"

const styles: Record<Variant, string> = {
  primary: "bg-accent text-white hover:bg-accent-light",
  secondary: "bg-ink text-white hover:bg-ink-soft",
  ghost: "bg-transparent text-ink-soft hover:bg-paper-soft",
  danger: "bg-red-600 text-white hover:bg-red-700",
}

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  children: ReactNode
}

export function Button({ variant = "primary", className, children, ...rest }: Props) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
        styles[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}
