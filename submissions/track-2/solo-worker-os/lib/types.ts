export type ProjectStatus = 'active' | 'delivered' | 'invoiced' | 'paid';

export interface Project {
  id: string;
  user_id?: string;
  client_name: string;
  project_type: string;
  budget: number;
  currency: string;
  deadline: string; // ISO date YYYY-MM-DD
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  casper_address?: string; // Client's Casper Network public key (for on-chain payment verification)
}

export type InvoiceStatus = 'draft' | 'sent' | 'paid' | 'overdue' | 'cancelled';

export interface Invoice {
  id: string;
  user_id?: string;
  project_id: string;
  invoice_number: string;
  amount: number;
  currency: string;
  status: InvoiceStatus;
  issued_date: string;
  due_date?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
}

export type PaymentMethod = 'bank_transfer' | 'wechat' | 'alipay' | 'stripe' | 'cash' | 'other';

export interface Payment {
  id: string;
  user_id?: string;
  project_id: string;
  invoice_id?: string;
  amount: number;
  currency: string;
  method: PaymentMethod;
  received_date: string;
  notes?: string;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  project_id: string | null;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export interface AgentAction {
  id: string;
  project_id: string | null;
  action_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export type DeliverableType = 'final_delivery' | 'draft' | 'source_file' | 'documentation' | 'other';
export type DeliverableStatus = 'filed' | 'sent' | 'accepted' | 'rejected';

export interface Deliverable {
  id: string;
  user_id?: string;
  project_id: string;
  title: string;
  url?: string | null;
  content?: string | null;
  type: DeliverableType;
  status: DeliverableStatus;
  notes?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}
