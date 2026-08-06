/**
 * Contact / community links.
 * Override at build time via VITE_CONTACT_* env vars;
 * falls back to hardcoded defaults so it works out of the box.
 */
export const CONTACT = {
  wechat: import.meta.env.VITE_CONTACT_WECHAT || '15976887109',
  telegram: import.meta.env.VITE_CONTACT_TELEGRAM || '@ethanyeang',
  twitter: import.meta.env.VITE_CONTACT_TWITTER || '@ethanyeang',
  discord: import.meta.env.VITE_CONTACT_DISCORD || '@ethanyeang',
} as const
