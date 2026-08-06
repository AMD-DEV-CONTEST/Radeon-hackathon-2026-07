export interface ExchangeRates {
  base: string;
  date: string;
  rates: Record<string, number>;
}

/**
 * Fetch live exchange rates from frankfurter.app (free, no API key).
 * Falls back to static approximate rates on network failure.
 */
export async function getExchangeRates(
  base = 'USD',
  targets = ['CNY', 'EUR', 'GBP', 'SGD', 'JPY', 'HKD']
): Promise<ExchangeRates> {
  const to = targets.filter((t) => t !== base).join(',');
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5_000);
    let res: Response;
    try {
      res = await fetch(`https://api.frankfurter.app/latest?from=${base}&to=${to}`, {
        next: { revalidate: 3600 },
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeoutId);
    }
    if (!res.ok) throw new Error('fetch failed');
    const json = await res.json() as { base: string; date: string; rates: Record<string, number> };
    return json;
  } catch {
    // Static fallback (approximate as of mid-2025)
    const fallback: Record<string, Record<string, number>> = {
      USD: { CNY: 7.25, EUR: 0.93, GBP: 0.79, SGD: 1.35, JPY: 155, HKD: 7.82 },
      CNY: { USD: 0.138, EUR: 0.128, GBP: 0.109, SGD: 0.186, JPY: 21.4, HKD: 1.08 },
      EUR: { USD: 1.075, CNY: 7.79, GBP: 0.85, SGD: 1.45, JPY: 166, HKD: 8.41 },
      SGD: { USD: 0.74, CNY: 5.37, EUR: 0.69, GBP: 0.585, JPY: 115, HKD: 5.79 },
    };
    const rates = fallback[base] ?? fallback['USD'];
    const filtered = Object.fromEntries(
      Object.entries(rates).filter(([k]) => targets.includes(k))
    );
    return { base, date: 'fallback', rates: filtered };
  }
}

// ── Industry Benchmarks ───────────────────────────────────────

export interface BenchmarkEntry {
  category: string;
  low: number;
  mid: number;
  high: number;
  unit: string;
  currency: string;
  notes: string;
}

const BENCHMARKS: BenchmarkEntry[] = [
  { category: 'Logo Design',        low: 500,   mid: 1500,  high: 5000,  unit: 'project', currency: 'USD', notes: 'Entry-level to senior brand identity' },
  { category: 'Website Design',     low: 2000,  mid: 8000,  high: 25000, unit: 'project', currency: 'USD', notes: 'Landing page to full custom site' },
  { category: 'Web Development',    low: 3000,  mid: 12000, high: 50000, unit: 'project', currency: 'USD', notes: 'Frontend/fullstack, complexity-dependent' },
  { category: 'Mobile App',         low: 8000,  mid: 30000, high: 120000,unit: 'project', currency: 'USD', notes: 'MVP to production-grade app' },
  { category: 'Copywriting',        low: 50,    mid: 150,   high: 500,   unit: 'hour',    currency: 'USD', notes: 'General to specialist copy' },
  { category: 'Content Writing',    low: 30,    mid: 80,    high: 200,   unit: 'hour',    currency: 'USD', notes: 'Blog posts, articles, SEO content' },
  { category: 'Consulting',         low: 100,   mid: 250,   high: 600,   unit: 'hour',    currency: 'USD', notes: 'Business / tech strategy' },
  { category: 'Video Editing',      low: 40,    mid: 100,   high: 300,   unit: 'hour',    currency: 'USD', notes: 'Social clips to commercial production' },
  { category: 'UI/UX Design',       low: 75,    mid: 150,   high: 400,   unit: 'hour',    currency: 'USD', notes: 'Wireframes to full design system' },
  { category: 'Data Analysis',      low: 60,    mid: 150,   high: 350,   unit: 'hour',    currency: 'USD', notes: 'Reporting to advanced analytics' },
  { category: 'SEO / Marketing',    low: 500,   mid: 2000,  high: 8000,  unit: 'month',   currency: 'USD', notes: 'Retainer-based digital marketing' },
  { category: 'Photography',        low: 300,   mid: 1000,  high: 5000,  unit: 'day',     currency: 'USD', notes: 'Half/full day shoot, complexity varies' },
];

/**
 * Return benchmarks matching a keyword (fuzzy substring match on category).
 * Returns all benchmarks if no keyword given.
 */
export function getIndustryBenchmarks(keyword?: string): BenchmarkEntry[] {
  if (!keyword) return BENCHMARKS;
  const q = keyword.toLowerCase();
  const match = BENCHMARKS.filter((b) => b.category.toLowerCase().includes(q));
  return match.length > 0 ? match : BENCHMARKS;
}
