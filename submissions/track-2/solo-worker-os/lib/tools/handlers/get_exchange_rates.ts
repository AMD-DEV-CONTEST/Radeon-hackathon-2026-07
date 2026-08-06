import { z } from 'zod';
import { getExchangeRates } from '@/lib/market-data';
import type { ToolConfig } from '../types';

// ─── Zod schema ────────────────────────────────────────────────────────────────
const ExchangeRatesSchema = z.object({
  base:    z.string().min(2).max(5),
  targets: z.array(z.string()).optional(),
});

// ─── Tool configuration ───────────────────────────────────────────────────────
export const getExchangeRatesTool: ToolConfig = {
  name: 'get_exchange_rates',
  description:
    'Get live currency exchange rates. Use when helping price a project in a foreign currency or convert between currencies.',
  input_schema: {
    type: 'object',
    properties: {
      base:    { type: 'string', description: 'Base currency ISO code, e.g. USD, CNY, SGD.' },
      targets: {
        type: 'array',
        items: { type: 'string' },
        description: 'Target currency codes to convert to, e.g. ["CNY","EUR","SGD"].',
      },
    },
    required: ['base'],
  },
  subagent: 'general',
  tags: ['pricing', 'exchange_rates'],
  modes: ['default', 'qwen', 'casper'],
  async handler(input) {
    const parsed = ExchangeRatesSchema.safeParse(input);
    if (!parsed.success) throw new Error(`Invalid input: ${parsed.error.message}`);
    const base = parsed.data.base.toUpperCase();
    const targets = (parsed.data.targets ?? ['CNY', 'EUR', 'GBP', 'SGD']).map((t) => t.toUpperCase());
    const rates = await getExchangeRates(base, targets);
    const lines = Object.entries(rates.rates).map(([cur, rate]) => `1 ${base} = ${rate.toFixed(4)} ${cur}`).join('\n');
    return {
      toolResult: `Live exchange rates (${rates.date}):\n${lines}`,
      clientSummary: `Fetched ${base} exchange rates vs ${targets.join(', ')}.`,
    };
  },
};

export default getExchangeRatesTool;
