export function daysRemaining(deadline: string): number {
  const d = new Date(deadline + 'T00:00:00');
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return Math.ceil((d.getTime() - now.getTime()) / 86_400_000);
}

// Map currency code → locale that produces the cleanest symbol (no "CN¥", no "US$")
const CURRENCY_LOCALE: Record<string, string> = {
  CNY: 'zh-CN',
  HKD: 'zh-HK',
  TWD: 'zh-TW',
  USD: 'en-US',
  SGD: 'en-SG',
  EUR: 'de-DE',
  GBP: 'en-GB',
  JPY: 'ja-JP',
  KRW: 'ko-KR',
};

export function formatMoney(amount: number, currency: string): string {
  const locale = CURRENCY_LOCALE[currency.toUpperCase()] ?? 'en-US';
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      maximumFractionDigits: currency === 'JPY' || currency === 'KRW' ? 0 : 2,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toLocaleString()}`;
  }
}

export function timeAgo(iso: string, lang: 'en' | 'zh' = 'en'): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (lang === 'zh') {
    if (mins < 1) return '刚刚';
    if (mins < 60) return `${mins}分钟前`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}小时前`;
    const days = Math.floor(hrs / 24);
    return `${days}天前`;
  }
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export function formatChatTime(timestamp: number): string {
  if (!timestamp) return '';
  return new Intl.DateTimeFormat('en', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(timestamp));
}

export function getGreeting(lang: 'en' | 'zh' = 'en'): string {
  if (lang === 'zh') {
    return '今天想完成什么？';
  }
  return 'What would you like to get done today?';
}
