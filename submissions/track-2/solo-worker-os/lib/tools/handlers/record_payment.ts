import { z } from 'zod';
import type { SupabaseClient } from '@supabase/supabase-js';
import type { ToolConfig } from '../types';
import { resolveProject } from '@/lib/tools/resolve-project';
import { syncWorkflowForProject, markWorkflowCheck } from '@/lib/workflow-sync';

// ─── Zod schema ────────────────────────────────────────────────────────────────
const PaymentSchema = z.object({
  project_id: z.string().uuid().optional(),
  client_name: z.string().optional(),
  project_type: z.string().optional(),
  amount: z.number().positive().max(10_000_000).optional(),
  currency: z.string().min(2).max(5).optional(),
  method: z.enum(['bank_transfer', 'wechat', 'alipay', 'stripe', 'cash', 'other']).optional(),
  received_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
  notes: z.string().max(500).optional(),
}).refine(
  (data) => data.project_id || data.client_name,
  { message: 'Either project_id or client_name must be provided' }
);

// ─── Tool configuration ───────────────────────────────────────────────────────
export const recordPaymentTool: ToolConfig = {
  name: 'record_payment',
  description: "Record a payment received from a client. Pass project_id (UUID) OR client_name to look up the project. The amount defaults to the project budget if not specified. When the user says '张明的款收到了' or '刘洋付了5000元', call this tool. Recording payment automatically marks the project as 'paid'.",
  input_schema: {
    type: 'object',
    properties: {
      project_id: { type: 'string', description: 'UUID of the project. Optional if client_name is given.' },
      client_name: { type: 'string', description: 'Client name to look up the project.' },
      project_type: { type: 'string', description: 'Optional: project type to disambiguate when a client has multiple projects.' },
      amount: { type: 'number', description: 'Payment amount. Defaults to the project budget.' },
      currency: { type: 'string', description: 'ISO 4217 code, e.g. CNY, USD, EUR. Defaults to project currency.' },
      method: { type: 'string', enum: ['bank_transfer', 'wechat', 'alipay', 'stripe', 'cash', 'other'], description: 'Payment method. Defaults to bank_transfer.' },
      received_date: { type: 'string', description: 'Date payment was received (YYYY-MM-DD). Defaults to today.' },
      notes: { type: 'string', description: 'Optional notes about the payment.' },
    },
    required: [],
  },
  subagent: 'general',
  tags: ['payment', 'finance', 'record'],
  modes: ['default', 'qwen', 'casper'],
  async handler(input, ctx) {
    const supabase = ctx.supabase as SupabaseClient;
    const { data: authData } = await supabase.auth.getUser().catch(() => ({ data: { user: null } }));
    const userId = authData?.user?.id;

    const parsed = PaymentSchema.safeParse(input);
    if (!parsed.success) throw new Error(`Invalid input: ${parsed.error.message}`);
    const p = await resolveProject(supabase, parsed.data);

    // State machine constraint: only projects in 'invoiced' or 'delivered' status can receive payment
    if (!['invoiced', 'delivered'].includes(p.status)) {
      throw new Error(
        `Cannot record payment: project "${p.project_type}" for ${p.client_name} has status "${p.status}". ` +
        `Must be "invoiced" or "delivered" first.`
      );
    }

    const amount = parsed.data.amount ?? Number(p.budget);
    const currency = parsed.data.currency ?? p.currency;
    const method = parsed.data.method ?? 'bank_transfer';
    const receivedDate = parsed.data.received_date ?? new Date().toISOString().slice(0, 10);

    // Check if there's an existing invoice for this project to link
    const { data: existingInvoice } = await supabase
      .from('invoices')
      .select('id')
      .eq('project_id', p.id)
      .order('created_at', { ascending: false })
      .limit(1)
      .single();

    const { data, error } = await supabase.from('payments').insert({
      project_id: p.id,
      invoice_id: existingInvoice?.id ?? null,
      amount,
      currency,
      method,
      received_date: receivedDate,
      notes: parsed.data.notes ?? null,
      ...(userId && { user_id: userId }),
    }).select().single();
    if (error) throw new Error(error.message);

    // Mark project as paid
    await supabase.from('projects').update({ status: 'paid' }).eq('id', p.id);

    // Mark linked invoice as paid if exists
    if (existingInvoice?.id) {
      await supabase.from('invoices').update({ status: 'paid' }).eq('id', existingInvoice.id);
    }

    await supabase.from('agent_actions').insert({
      project_id: p.id,
      action_type: 'payment_recorded',
      payload: { payment_id: data.id, amount, currency, method, received_date: receivedDate },
      ...(userId && { user_id: userId }),
    });

    // Sync workflow: advance to 'paid' stage and mark payment_received check
    await syncWorkflowForProject(supabase, p.id, 'paid');
    await markWorkflowCheck(supabase, p.id, 'paid:payment_received');

    return {
      toolResult: `Payment recorded: ${currency} ${amount.toFixed(2)} from ${p.client_name} via ${method} on ${receivedDate}. Project marked as paid.`,
      clientSummary: `Recorded payment of ${currency} ${amount.toFixed(2)} from ${p.client_name}. Project marked as paid.`,
    };
  },
};

export default recordPaymentTool;
