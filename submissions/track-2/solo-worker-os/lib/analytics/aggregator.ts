/**
 * Anonymous business data aggregator.
 *
 * Aggregates project/invoice/payment data across all users to produce
 * industry benchmark reports. All data is anonymized — no client names,
 * no user IDs, no project-specific details.
 *
 * This is the "content with zero marginal cost" strategy: the system
 * produces real ROI data as a byproduct of running the business, which
 * is the hardest asset for competitors to copy.
 */

import type { SupabaseClient } from '@supabase/supabase-js';
import type { Project, Invoice, Payment, Deliverable } from '@/lib/types';

export interface BenchmarkReport {
  generatedAt: string;
  period: string;
  metrics: {
    totalProjects: number;
    activeProjects: number;
    completedProjects: number;
    paidProjects: number;
    averageBudget: number;
    medianBudget: number;
    averageProjectDuration: number; // days from created to paid
    contractSigningRate: number; // % of projects with contracts
    invoicePaymentRate: number; // % of invoices that are paid
    averagePaymentCycle: number; // days from invoice to payment
  };
  projectTypeDistribution: Array<{ type: string; count: number; avgBudget: number }>;
  statusDistribution: Array<{ status: string; count: number; percentage: number }>;
  budgetRanges: Array<{ range: string; count: number; percentage: number }>;
  currencyDistribution: Array<{ currency: string; count: number; total: number }>;
  monthlyRevenue: Array<{ month: string; revenue: number; projectCount: number }>;
  toolUsageRanking: Array<{ tool: string; count: number }>;
  deliverableStats: {
    total: number;
    byType: Array<{ type: string; count: number }>;
    acceptanceRate: number;
  };
}

export async function generateBenchmarkReport(
  supabase: SupabaseClient,
  periodMonths = 3
): Promise<BenchmarkReport> {
  const periodStart = new Date();
  periodStart.setMonth(periodStart.getMonth() - periodMonths);
  const periodStartISO = periodStart.toISOString();

  // Parallel data fetch
  const [
    { data: projects },
    { data: invoices },
    { data: payments },
    { data: deliverables },
    { data: actions },
  ] = await Promise.all([
    supabase.from('projects').select('*'),
    supabase.from('invoices').select('*'),
    supabase.from('payments').select('*'),
    supabase.from('deliverables').select('*'),
    supabase.from('agent_actions').select('action_type'),
  ]);

  const projectList = (projects as Project[]) ?? [];
  const invoiceList = (invoices as Invoice[]) ?? [];
  const paymentList = (payments as Payment[]) ?? [];
  const deliverableList = (deliverables as Deliverable[]) ?? [];
  const actionList = (actions as Array<{ action_type: string }>) ?? [];

  // ── Core metrics ─────────────────────────────────────────────────────────
  const budgets = projectList.map((p) => Number(p.budget)).filter((b) => b > 0);
  const sortedBudgets = [...budgets].sort((a, b) => a - b);
  const avgBudget = budgets.length > 0 ? budgets.reduce((s, b) => s + b, 0) / budgets.length : 0;
  const medianBudget = sortedBudgets.length > 0
    ? sortedBudgets[Math.floor(sortedBudgets.length / 2)]
    : 0;

  const activeCount = projectList.filter((p) => p.status === 'active').length;
  const paidCount = projectList.filter((p) => p.status === 'paid').length;
  const completedCount = projectList.filter((p) => p.status === 'paid' || p.status === 'delivered').length;

  // Average project duration (created → paid)
  const paidProjects = projectList.filter((p) => p.status === 'paid');
  const durations = paidProjects.map((p) => {
    const created = new Date(p.created_at).getTime();
    const updated = new Date(p.updated_at).getTime();
    return Math.round((updated - created) / 86400000);
  }).filter((d) => d >= 0);
  const avgDuration = durations.length > 0 ? durations.reduce((s, d) => s + d, 0) / durations.length : 0;

  // Contract signing rate (projects with contract_generated action)
  const contractActions = actionList.filter((a) => a.action_type === 'contract_generated').length;
  const contractRate = projectList.length > 0 ? contractActions / projectList.length : 0;

  // Invoice payment rate
  const paidInvoices = invoiceList.filter((i) => i.status === 'paid').length;
  const invoiceRate = invoiceList.length > 0 ? paidInvoices / invoiceList.length : 0;

  // Average payment cycle (invoice issued → payment received)
  const paymentCycles: number[] = [];
  for (const payment of paymentList) {
    if (!payment.invoice_id) continue;
    const invoice = invoiceList.find((i) => i.id === payment.invoice_id);
    if (!invoice) continue;
    const issued = new Date(invoice.issued_date).getTime();
    const received = new Date(payment.received_date).getTime();
    const cycle = Math.round((received - issued) / 86400000);
    if (cycle >= 0) paymentCycles.push(cycle);
  }
  const avgPaymentCycle = paymentCycles.length > 0
    ? paymentCycles.reduce((s, c) => s + c, 0) / paymentCycles.length
    : 0;

  // ── Project type distribution ─────────────────────────────────────────────
  const typeMap = new Map<string, { count: number; totalBudget: number }>();
  for (const p of projectList) {
    const key = p.project_type;
    const existing = typeMap.get(key) ?? { count: 0, totalBudget: 0 };
    typeMap.set(key, {
      count: existing.count + 1,
      totalBudget: existing.totalBudget + Number(p.budget),
    });
  }
  const projectTypeDistribution = [...typeMap.entries()]
    .map(([type, v]) => ({ type, count: v.count, avgBudget: v.count > 0 ? v.totalBudget / v.count : 0 }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);

  // ── Status distribution ───────────────────────────────────────────────────
  const statusCounts = new Map<string, number>();
  for (const p of projectList) {
    statusCounts.set(p.status, (statusCounts.get(p.status) ?? 0) + 1);
  }
  const statusDistribution = [...statusCounts.entries()].map(([status, count]) => ({
    status,
    count,
    percentage: projectList.length > 0 ? count / projectList.length : 0,
  }));

  // ── Budget ranges ─────────────────────────────────────────────────────────
  const ranges = [
    { range: '0-5K', min: 0, max: 5000 },
    { range: '5K-10K', min: 5000, max: 10000 },
    { range: '10K-20K', min: 10000, max: 20000 },
    { range: '20K-50K', min: 20000, max: 50000 },
    { range: '50K+', min: 50000, max: Infinity },
  ];
  const budgetRanges = ranges.map((r) => {
    const count = projectList.filter((p) => Number(p.budget) >= r.min && Number(p.budget) < r.max).length;
    return { range: r.range, count, percentage: projectList.length > 0 ? count / projectList.length : 0 };
  });

  // ── Currency distribution ─────────────────────────────────────────────────
  const currencyMap = new Map<string, { count: number; total: number }>();
  for (const p of projectList) {
    const existing = currencyMap.get(p.currency) ?? { count: 0, total: 0 };
    currencyMap.set(p.currency, {
      count: existing.count + 1,
      total: existing.total + Number(p.budget),
    });
  }
  const currencyDistribution = [...currencyMap.entries()].map(([currency, v]) => ({
    currency,
    count: v.count,
    total: v.total,
  }));

  // ── Monthly revenue ────────────────────────────────────────────────────────
  const monthlyMap = new Map<string, { revenue: number; projectCount: number }>();
  for (const payment of paymentList) {
    const month = payment.received_date.slice(0, 7);
    const existing = monthlyMap.get(month) ?? { revenue: 0, projectCount: 0 };
    monthlyMap.set(month, {
      revenue: existing.revenue + Number(payment.amount),
      projectCount: existing.projectCount + 1,
    });
  }
  const monthlyRevenue = [...monthlyMap.entries()]
    .map(([month, v]) => ({ month, revenue: v.revenue, projectCount: v.projectCount }))
    .sort((a, b) => a.month.localeCompare(b.month))
    .slice(-6);

  // ── Tool usage ranking ────────────────────────────────────────────────────
  const toolCounts = new Map<string, number>();
  for (const a of actionList) {
    toolCounts.set(a.action_type, (toolCounts.get(a.action_type) ?? 0) + 1);
  }
  const toolUsageRanking = [...toolCounts.entries()]
    .map(([tool, count]) => ({ tool, count }))
    .sort((a, b) => b.count - a.count);

  // ── Deliverable stats ─────────────────────────────────────────────────────
  const deliverableByType = new Map<string, number>();
  for (const d of deliverableList) {
    deliverableByType.set(d.type, (deliverableByType.get(d.type) ?? 0) + 1);
  }
  const acceptedDeliverables = deliverableList.filter((d) => d.status === 'accepted').length;
  const deliverableStats = {
    total: deliverableList.length,
    byType: [...deliverableByType.entries()].map(([type, count]) => ({ type, count })),
    acceptanceRate: deliverableList.length > 0 ? acceptedDeliverables / deliverableList.length : 0,
  };

  return {
    generatedAt: new Date().toISOString(),
    period: `${periodMonths}M`,
    metrics: {
      totalProjects: projectList.length,
      activeProjects: activeCount,
      completedProjects: completedCount,
      paidProjects: paidCount,
      averageBudget: Math.round(avgBudget),
      medianBudget: Math.round(medianBudget),
      averageProjectDuration: Math.round(avgDuration),
      contractSigningRate: Math.round(contractRate * 100) / 100,
      invoicePaymentRate: Math.round(invoiceRate * 100) / 100,
      averagePaymentCycle: Math.round(avgPaymentCycle),
    },
    projectTypeDistribution,
    statusDistribution,
    budgetRanges,
    currencyDistribution,
    monthlyRevenue,
    toolUsageRanking,
    deliverableStats,
  };
}
