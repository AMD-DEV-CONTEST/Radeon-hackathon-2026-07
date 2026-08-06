import { headers } from 'next/headers';
import { translations, type Lang } from '@/lib/i18n';

/**
 * Reads the language from the `solo-lang` cookie on the server side.
 * Defaults to 'zh' (Chinese) — primary audience is Chinese-speaking solo workers.
 */
export function getServerLang(): Lang {
  const headerList = headers();
  const cookie = headerList.get('cookie') ?? '';
  const match = cookie.match(/solo-lang=(en|zh)/);
  return (match?.[1] as Lang) ?? 'zh';
}

export function getServerT() {
  return translations[getServerLang()];
}
