import { z } from 'zod';
import { getIndustryBenchmarks } from '@/lib/market-data';
import type { ToolConfig } from '../types';

// ─── Zod schema ────────────────────────────────────────────────────────────────
const PricingBenchmarkSchema = z.object({
  category: z.string().min(1).max(200),
});

// ─── Tool configuration ───────────────────────────────────────────────────────
export const getPricingBenchmarkTool: ToolConfig = {
  name: 'get_pricing_benchmark',
  description:
    'Get industry benchmark rates for freelance services (low / mid / high price ranges). Use when helping the user decide on a project price or validate their quote.',
  input_schema: {
    type: 'object',
    properties: {
      category: { type: 'string', description: 'Service type keyword, e.g. "logo", "website", "copywriting".' },
    },
    required: ['category'],
  },
  subagent: 'general',
  tags: ['pricing', 'benchmark'],
  modes: ['default', 'qwen', 'casper'],
  async handler(input) {
    const parsed = PricingBenchmarkSchema.safeParse(input);
    if (!parsed.success) throw new Error(`Invalid input: ${parsed.error.message}`);
    const benchmarks = getIndustryBenchmarks(parsed.data.category);
    const lines = benchmarks.slice(0, 5).map(
      (b) => `${b.category}: ${b.currency} ${b.low}–${b.mid}–${b.high} per ${b.unit} (${b.notes})`
    ).join('\n');
    return {
      toolResult: `Industry pricing benchmarks for "${parsed.data.category}":\n${lines}`,
      clientSummary: `Fetched pricing benchmarks for: "${parsed.data.category}".`,
    };
  },
};

export default getPricingBenchmarkTool;
