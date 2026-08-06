/**
 * In-memory mock Supabase client for demo mode.
 *
 * Used when DEMO_MODE=true is set in .env.local.
 * Pre-seeds with demo data from supabase/seed.sql.
 * All data is in-memory and resets on server restart.
 */

import { TfidfIndex } from './rag/tfidf';

// ─── In-memory data store ────────────────────────────────────────────────────

const now = new Date().toISOString();
const daysAgo = (n: number) => new Date(Date.now() - n * 86400000).toISOString();

interface MockRow {
  [key: string]: unknown;
}

/** Shape of a knowledge_docs seed row (also used by the TF-IDF index). */
export interface KnowledgeSeedDoc {
  id: string;
  title: string;
  content: string;
  doc_type: string;
  tags: string[];
  created_at: string;
}

// Use globalThis to share data across module instances (Next.js dev mode HMR)
const GLOBAL_KEY = '__SOLO_MOCK_TABLES__';
type TablesMap = Record<string, MockRow[]>;

function seedTables(): TablesMap {
  return {
  projects: [
    { id: 'a1000000-0000-0000-0000-000000000001', client_name: '张明', project_type: '企业官网重构与上线', budget: 35000, currency: 'CNY', deadline: '2026-08-30', status: 'active', casper_address: null, created_at: daysAgo(50), updated_at: daysAgo(3) },
    { id: 'a1000000-0000-0000-0000-000000000002', client_name: '李薇', project_type: '产品官网设计与开发', budget: 18000, currency: 'CNY', deadline: '2026-08-15', status: 'active', casper_address: null, created_at: daysAgo(31), updated_at: daysAgo(7) },
    { id: 'a1000000-0000-0000-0000-000000000003', client_name: '王浩', project_type: '小程序商城开发', budget: 15000, currency: 'CNY', deadline: '2026-07-20', status: 'invoiced', casper_address: null, created_at: daysAgo(45), updated_at: daysAgo(5) },
    { id: 'a1000000-0000-0000-0000-000000000004', client_name: '陈雨', project_type: '品牌视觉系统设计', budget: 8000, currency: 'CNY', deadline: '2026-06-30', status: 'paid', casper_address: null, created_at: daysAgo(67), updated_at: daysAgo(30) },
    { id: 'a1000000-0000-0000-0000-000000000005', client_name: '刘洋', project_type: '产品宣传视频制作', budget: 6000, currency: 'CNY', deadline: '2026-07-25', status: 'delivered', casper_address: null, created_at: daysAgo(28), updated_at: daysAgo(10) },
    { id: 'a1000000-0000-0000-0000-000000000006', client_name: '赵雪', project_type: '品牌发布会演示设计', budget: 5000, currency: 'CNY', deadline: '2026-07-28', status: 'active', casper_address: null, created_at: daysAgo(13), updated_at: daysAgo(2) },
  ],
  invoices: [
    { id: 'c1000000-0000-0000-0000-000000000001', project_id: 'a1000000-0000-0000-0000-000000000004', invoice_number: 'INV-202606-A1B2', amount: 8000, currency: 'CNY', status: 'paid', issued_date: '2026-06-15', due_date: '2026-06-30', notes: null, created_at: daysAgo(40), updated_at: daysAgo(30) },
    { id: 'c1000000-0000-0000-0000-000000000002', project_id: 'a1000000-0000-0000-0000-000000000003', invoice_number: 'INV-202607-C3D4', amount: 15000, currency: 'CNY', status: 'sent', issued_date: '2026-07-10', due_date: '2026-07-25', notes: null, created_at: daysAgo(17), updated_at: daysAgo(5) },
  ],
  payments: [
    { id: 'd1000000-0000-0000-0000-000000000001', project_id: 'a1000000-0000-0000-0000-000000000004', invoice_id: 'c1000000-0000-0000-0000-000000000001', amount: 8000, currency: 'CNY', method: 'wechat', received_date: '2026-06-28', notes: null, created_at: daysAgo(30) },
    { id: 'd1000000-0000-0000-0000-000000000002', project_id: 'a1000000-0000-0000-0000-000000000006', invoice_id: null, amount: 2500, currency: 'CNY', method: 'alipay', received_date: '2026-07-25', notes: '预付款 50%', created_at: daysAgo(3) },
  ],
  messages: [],
  agent_actions: [
    { id: 'act-001', project_id: 'a1000000-0000-0000-0000-000000000001', action_type: 'project_created', payload: { client: '张明', type: '企业官网重构与上线', budget: 35000, currency: 'CNY' }, created_at: daysAgo(50) },
    { id: 'act-002', project_id: 'a1000000-0000-0000-0000-000000000001', action_type: 'contract_generated', payload: { contract: '服务合同 - 张明' }, created_at: daysAgo(49) },
    { id: 'act-003', project_id: 'a1000000-0000-0000-0000-000000000001', action_type: 'status_updated', payload: { status: 'active' }, created_at: daysAgo(3) },
    { id: 'act-004', project_id: 'a1000000-0000-0000-0000-000000000002', action_type: 'project_created', payload: { client: '李薇', type: '产品官网设计与开发', budget: 18000, currency: 'CNY' }, created_at: daysAgo(31) },
    { id: 'act-005', project_id: 'a1000000-0000-0000-0000-000000000004', action_type: 'project_created', payload: { client: '陈雨', type: '品牌视觉系统设计', budget: 8000, currency: 'CNY' }, created_at: daysAgo(67) },
    { id: 'act-006', project_id: 'a1000000-0000-0000-0000-000000000003', action_type: 'contract_generated', payload: { contract: '服务合同 - 王浩' }, created_at: daysAgo(44) },
    { id: 'act-007', project_id: 'a1000000-0000-0000-0000-000000000005', action_type: 'project_created', payload: { client: '刘洋', type: '产品宣传视频制作', budget: 6000, currency: 'CNY' }, created_at: daysAgo(28) },
    { id: 'act-008', project_id: 'a1000000-0000-0000-0000-000000000005', action_type: 'status_updated', payload: { status: 'delivered' }, created_at: daysAgo(10) },
    { id: 'act-009', project_id: 'a1000000-0000-0000-0000-000000000006', action_type: 'project_created', payload: { client: '赵雪', type: '品牌发布会演示设计', budget: 5000, currency: 'CNY' }, created_at: daysAgo(13) },
    { id: 'act-010', project_id: 'a1000000-0000-0000-0000-000000000006', action_type: 'followup_generated', payload: { tone: 'polite' }, created_at: daysAgo(5) },
    { id: 'act-011', project_id: 'a1000000-0000-0000-0000-000000000003', action_type: 'status_updated', payload: { status: 'invoiced' }, created_at: daysAgo(5) },
    { id: 'act-012', project_id: 'a1000000-0000-0000-0000-000000000004', action_type: 'status_updated', payload: { status: 'paid' }, created_at: daysAgo(30) },
    { id: 'act-013', project_id: 'a1000000-0000-0000-0000-000000000004', action_type: 'invoice_generated', payload: { invoice_number: 'INV-202606-A1B2', amount: 8000, currency: 'CNY' }, created_at: daysAgo(40) },
    { id: 'act-014', project_id: 'a1000000-0000-0000-0000-000000000004', action_type: 'payment_recorded', payload: { amount: 8000, currency: 'CNY', method: 'wechat' }, created_at: daysAgo(30) },
    { id: 'act-015', project_id: 'a1000000-0000-0000-0000-000000000003', action_type: 'invoice_generated', payload: { invoice_number: 'INV-202607-C3D4', amount: 15000, currency: 'CNY' }, created_at: daysAgo(17) },
    { id: 'act-016', project_id: 'a1000000-0000-0000-0000-000000000006', action_type: 'payment_recorded', payload: { amount: 2500, currency: 'CNY', method: 'alipay', note: '预付款 50%' }, created_at: daysAgo(3) },
  ],
  knowledge_docs: [
    {
      id: 'b1000000-0000-0000-0000-000000000001',
      title: '标准服务合同模板',
      content: '# 服务合同模板\n\n## 合作条款\n- 项目启动前支付 50% 预付款\n- 验收完成后支付 50% 尾款\n- 含 2 轮免费修改\n- 额外修改按 200 元/小时计费\n\n## 取消条款\n任一方提前 7 天通知可取消合作。预付款在工作启动后不予退还。\n\n## 知识产权\n尾款结清后，所有交付物归客户所有。我方保留在作品集中展示的权利。',
      doc_type: 'template',
      tags: ['合同', '模板', '标准'],
      created_at: daysAgo(80),
    },
    {
      id: 'b1000000-0000-0000-0000-000000000002',
      title: '新客户沟通邮件模板',
      content: '主题：关于项目咨询的回复\n\n您好 [客户名]，\n\n感谢您的咨询！很高兴与您讨论项目需求。\n\n为了给出准确报价，请提供以下信息：\n- 项目范围和交付物\n- 期望完成时间\n- 预算范围\n- 参考案例或设计偏好\n\n我通常在 24 小时内回复咨询。\n\n祝好，\n[你的名字]',
      doc_type: 'email',
      tags: ['模板', '邮件', '咨询'],
      created_at: daysAgo(80),
    },
    {
      id: 'b1000000-0000-0000-0000-000000000003',
      title: '催款提醒模板',
      content: '# 催款提醒\n\n## 友好提醒（逾期 7 天）\n主题：温馨提醒 — [项目名] 的发票 #[编号]\n\n您好 [客户名]，\n友情提醒一下，[项目名] 的发票 #[编号] 已于 [日期] 到期。不着急，有任何问题随时沟通。\n\n## 正式催款（逾期 14 天）\n主题：逾期发票提醒 — #[编号]\n\n您好 [客户名]，\n跟进一下 [项目名] 的发票 #[编号]，到期日为 [日期]。截至目前已逾期 [天数] 天，请尽快安排付款。\n\n## 最终通知（逾期 30 天）\n主题：最终通知 — 发票 #[编号]\n\n您好 [客户名]，\n这是最终通知。如 7 天内未收到付款，我将暂停所有进行中的工作。',
      doc_type: 'template',
      tags: ['催款', '提醒', '发票'],
      created_at: daysAgo(80),
    },
    {
      id: 'b1000000-0000-0000-0000-000000000004',
      title: '客户偏好与备注',
      content: '# 客户备注\n\n## 张明\n- 偏好微信沟通\n- 技术背景强，关注架构设计\n- 付款准时\n\n## 李薇\n- 决策果断，推进速度快\n- 要求周报同步\n- 偏好支付宝转账\n\n## 王浩\n- 注重细节，文档要求高\n- 需要中英双语交付物\n- 偏好银行转账',
      doc_type: 'note',
      tags: ['客户', '偏好', '备注'],
      created_at: daysAgo(20),
    },
    {
      id: 'b1000000-0000-0000-0000-000000000005',
      title: '报价参考标准',
      content: '# 报价参考\n\n## 开发类\n- 网站开发：8,000-30,000 元\n- 移动应用：15,000-50,000 元\n- API 开发：5,000-20,000 元\n\n## 设计类\n- 品牌视觉：5,000-15,000 元\n- UI 设计：6,000-20,000 元\n- Logo 设计：2,000-8,000 元\n\n## 其他\n- 视频制作：3,000-10,000 元\n- PPT 设计：2,000-8,000 元\n\n注：以上为参考价，最终报价根据项目复杂度、周期和客户预算协商确定。',
      doc_type: 'note',
      tags: ['报价', '参考', '标准'],
      created_at: daysAgo(15),
    },
  ],
  notifications: [],
  deliverables: [
    { id: 'e1000000-0000-0000-0000-000000000001', project_id: 'a1000000-0000-0000-0000-000000000004', title: '品牌视觉系统终稿', url: 'https://example.com/brand-final.zip', content: null, type: 'final_delivery', status: 'accepted', notes: '客户已签收', version: 3, created_at: daysAgo(31), updated_at: daysAgo(30) },
    { id: 'e1000000-0000-0000-0000-000000000002', project_id: 'a1000000-0000-0000-0000-000000000005', title: '产品宣传视频成片', url: 'https://example.com/video-final.mp4', content: null, type: 'final_delivery', status: 'filed', notes: '高清版+压缩版', version: 2, created_at: daysAgo(10), updated_at: daysAgo(10) },
    { id: 'e1000000-0000-0000-0000-000000000003', project_id: 'a1000000-0000-0000-0000-000000000004', title: '品牌视觉系统源文件', url: 'https://example.com/brand-source.zip', content: null, type: 'source_file', status: 'filed', notes: 'AI + PSD 源文件', version: 1, created_at: daysAgo(31), updated_at: daysAgo(31) },
  ],
  api_keys: [
    { id: 'k1000000-0000-0000-0000-000000000001', user_id: null, key_hash: 'demo_hash_pro_key', key_prefix: 'sk_live_de', label: 'Pro Benchmark', tier: 'pro', daily_limit: 1000, requests_today: 12, last_used_at: daysAgo(1), created_at: daysAgo(15), revoked_at: null },
    { id: 'k1000000-0000-0000-0000-000000000002', user_id: null, key_hash: 'demo_hash_free_key', key_prefix: 'sk_live_fr', label: 'Free Preview', tier: 'free', daily_limit: 100, requests_today: 5, last_used_at: daysAgo(2), created_at: daysAgo(10), revoked_at: null },
  ],
  workflow_steps: [
    { id: 'wf-001', project_id: 'a1000000-0000-0000-0000-000000000001', stage: 'in_progress', checks: { 'kickoff:brief_received': true, 'kickoff:timeline_agreed': true, 'kickoff:deposit_invoiced': true, 'in_progress:work_started': true, 'in_progress:draft_complete': true, 'in_progress:internal_review': false }, created_at: daysAgo(50), updated_at: daysAgo(3) },
    { id: 'wf-002', project_id: 'a1000000-0000-0000-0000-000000000002', stage: 'in_progress', checks: { 'kickoff:brief_received': true, 'kickoff:timeline_agreed': true, 'kickoff:deposit_invoiced': true, 'in_progress:work_started': true, 'in_progress:draft_complete': false, 'in_progress:internal_review': false }, created_at: daysAgo(31), updated_at: daysAgo(7) },
    { id: 'wf-003', project_id: 'a1000000-0000-0000-0000-000000000003', stage: 'invoiced', checks: { 'kickoff:brief_received': true, 'kickoff:timeline_agreed': true, 'kickoff:deposit_invoiced': true, 'in_progress:work_started': true, 'in_progress:draft_complete': true, 'in_progress:internal_review': true, 'review:sent_to_client': true, 'review:feedback_received': true, 'review:revisions_applied': true, 'delivery:final_sent': true, 'delivery:signoff': true, 'delivery:assets_filed': true, 'invoiced:invoice_sent': true, 'invoiced:payment_terms_set': false }, created_at: daysAgo(45), updated_at: daysAgo(5) },
    { id: 'wf-004', project_id: 'a1000000-0000-0000-0000-000000000004', stage: 'paid', checks: { 'kickoff:brief_received': true, 'kickoff:timeline_agreed': true, 'kickoff:deposit_invoiced': true, 'in_progress:work_started': true, 'in_progress:draft_complete': true, 'in_progress:internal_review': true, 'review:sent_to_client': true, 'review:feedback_received': true, 'review:revisions_applied': true, 'delivery:final_sent': true, 'delivery:signoff': true, 'delivery:assets_filed': true, 'invoiced:invoice_sent': true, 'invoiced:payment_terms_set': true, 'paid:payment_received': true, 'paid:receipt_sent': true }, created_at: daysAgo(67), updated_at: daysAgo(30) },
    { id: 'wf-005', project_id: 'a1000000-0000-0000-0000-000000000005', stage: 'review', checks: { 'kickoff:brief_received': true, 'kickoff:timeline_agreed': true, 'kickoff:deposit_invoiced': true, 'in_progress:work_started': true, 'in_progress:draft_complete': true, 'in_progress:internal_review': true, 'review:sent_to_client': true, 'review:feedback_received': false, 'review:revisions_applied': false }, created_at: daysAgo(28), updated_at: daysAgo(10) },
    { id: 'wf-006', project_id: 'a1000000-0000-0000-0000-000000000006', stage: 'kickoff', checks: { 'kickoff:brief_received': true, 'kickoff:timeline_agreed': false, 'kickoff:deposit_invoiced': true }, created_at: daysAgo(13), updated_at: daysAgo(2) },
  ],
};
}

// Initialize global tables once; reuse across HMR reloads
const g = globalThis as Record<string, unknown>;
if (!g[GLOBAL_KEY]) {
  g[GLOBAL_KEY] = seedTables();
}
const tables: TablesMap = g[GLOBAL_KEY] as TablesMap;

/**
 * Snapshot of the seed knowledge_docs (the 5 rows above), captured at module
 * load before any runtime mutation. Exported so the TF-IDF index
 * (lib/rag/tfidf.ts) can pre-fill itself with identical demo data without a
 * circular runtime dependency.
 */
export const KNOWLEDGE_DOCS_SEED: KnowledgeSeedDoc[] = (
  tables.knowledge_docs as unknown as KnowledgeSeedDoc[]
).map((d) => ({ ...d, tags: [...d.tags] }));

function genId(_table: string): string {
  // 生成标准 UUID v4 格式，与真实 Supabase 的 gen_random_uuid() 行为一致
  // 避免 z.string().uuid() 校验失败（如 generate_contract 等工具）
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// ─── Mock Query Builder ──────────────────────────────────────────────────────

type Operation = 'select' | 'insert' | 'update' | 'delete' | 'upsert';

interface Filter {
  field: string;
  value: unknown;
  op: 'eq' | 'textsearch' | 'not';
  notOp?: string;
}

class MockQueryBuilder {
  private tableName: string;
  private op: Operation = 'select';
  private insertData: MockRow | null = null;
  private updateData: Partial<MockRow> | null = null;
  private filters: Filter[] = [];
  private orderField: string | null = null;
  private orderAscending = true;
  private limitN: number | null = null;
  private returnRows = false;

  constructor(table: string) {
    this.tableName = table;
  }

  // Make this thenable so `await builder` works (without .single())
  then(resolve: (v: { data: unknown; error: unknown }) => void, reject?: (e: unknown) => void): void {
    try {
      resolve(this.execute());
    } catch (e) {
      reject?.(e);
    }
  }

  // ── Chainable methods ──

  select(columns?: string): this {
    if (this.op === 'insert' || this.op === 'update' || this.op === 'delete') {
      // Modifier: return affected rows
      this.returnRows = true;
    } else {
      this.op = 'select';
    }
    // columns is ignored — we return all columns
    void columns;
    return this;
  }

  insert(data: MockRow): this {
    this.op = 'insert';
    this.insertData = data;
    return this;
  }

  update(data: Partial<MockRow>): this {
    this.op = 'update';
    this.updateData = data;
    return this;
  }

  delete(): this {
    this.op = 'delete';
    return this;
  }

  eq(field: string, value: unknown): this {
    this.filters.push({ field, value, op: 'eq' });
    return this;
  }

  not(field: string, operator: string, value: unknown): this {
    this.filters.push({ field, value, op: 'not', notOp: operator });
    return this;
  }

  order(field: string, options?: { ascending?: boolean }): this {
    this.orderField = field;
    this.orderAscending = options?.ascending ?? true;
    return this;
  }

  limit(count: number): this {
    this.limitN = count;
    return this;
  }

  textSearch(_field: string, query: string, _opts?: unknown): this {
    this.filters.push({ field: _field, value: query, op: 'textsearch' });
    return this;
  }

  // ── Terminal method ──

  async single(): Promise<{ data: MockRow | null; error: { message: string } | null }> {
    const result = this.execute();
    const rows = result.data as MockRow[];
    if (rows && Array.isArray(rows) && rows.length > 0) {
      return { data: rows[0], error: null };
    }
    return { data: null, error: { message: 'No rows found' } };
  }

  async maybeSingle(): Promise<{ data: MockRow | null; error: { message: string } | null }> {
    const result = this.execute();
    const rows = result.data as MockRow[];
    if (rows && Array.isArray(rows) && rows.length > 0) {
      return { data: rows[0], error: null };
    }
    return { data: null, error: null };
  }

  upsert(data: MockRow, _opts?: { onConflict?: string }): this {
    this.op = 'upsert';
    this.insertData = data;
    return this;
  }

  /**
   * Rank `rows` by TF-IDF cosine similarity to `query`, returning only rows
   * with a positive similarity score, best match first. Replaces the old
   * `terms.some(text.includes(term))` substring match so any Supabase-client
   * caller also benefits from the TF-IDF ranking (mixed CN/EN support).
   */
  private applyTfidfSearch(rows: MockRow[], query: string): MockRow[] {
    if (rows.length === 0) return rows;
    const index = TfidfIndex.empty();
    rows.forEach((row, i) => {
      index.addDocument({
        id: String(i),
        title: String(row.title ?? ''),
        content: String(row.content ?? ''),
        doc_type: row.doc_type as string | undefined,
        tags: row.tags as string[] | undefined,
      });
    });
    index.build();
    const results = index.search(query, rows.length);
    const ranked: MockRow[] = [];
    for (const r of results) {
      const idx = Number(r.docId);
      if (!Number.isNaN(idx) && rows[idx]) ranked.push(rows[idx]);
    }
    return ranked;
  }

  // ─── Execution ───

  private execute(): { data: unknown; error: unknown } {
    const tableData = tables[this.tableName] ?? [];

    // INSERT
    if ((this.op === 'insert' || this.op === 'upsert') && this.insertData) {
      // For upsert: update existing row if found by matching id or project_id
      if (this.op === 'upsert') {
        const matchField = this.insertData.project_id ? 'project_id' : 'id';
        const matchVal = this.insertData[matchField];
        const existingIdx = tableData.findIndex((row) => row[matchField] === matchVal);
        if (existingIdx >= 0) {
          tableData[existingIdx] = { ...tableData[existingIdx], ...this.insertData, updated_at: now };
          return { data: this.returnRows ? [tableData[existingIdx]] : null, error: null };
        }
      }
      const newRow: MockRow = {
        id: genId(this.tableName),
        created_at: now,
        updated_at: now,
        ...this.insertData,
      };
      tables[this.tableName] = [...tableData, newRow];
      return { data: this.returnRows ? [newRow] : null, error: null };
    }

    // Filter rows for SELECT, UPDATE, DELETE
    let rows = [...tableData];
    for (const f of this.filters) {
      if (f.op === 'textsearch') {
        rows = this.applyTfidfSearch(rows, String(f.value));
      } else if (f.op === 'not') {
        if (f.notOp === 'is') {
          // .not(field, 'is', null) → field IS NOT NULL
          rows = rows.filter((row) => row[f.field] != null);
        } else {
          // .not(field, 'eq', value) → field != value
          rows = rows.filter((row) => row[f.field] !== f.value);
        }
      } else {
        rows = rows.filter((row) => row[f.field] === f.value);
      }
    }

    // UPDATE
    if (this.op === 'update' && this.updateData) {
      const updatedRows: MockRow[] = rows.map((row) => ({
        ...row,
        ...this.updateData,
        updated_at: now,
      }));
      // Write back to table
      tables[this.tableName] = tableData.map((row) => {
        const match = updatedRows.find((u) => u.id === row.id);
        return match ?? row;
      });
      return { data: this.returnRows ? updatedRows : null, error: null };
    }

    // DELETE
    if (this.op === 'delete') {
      tables[this.tableName] = tableData.filter((row) => !rows.includes(row));
      return { data: this.returnRows ? rows : null, error: null };
    }

    // SELECT — apply ordering
    if (this.orderField) {
      const field = this.orderField;
      const asc = this.orderAscending;
      rows.sort((a, b) => {
        const av = a[field] as string | number | undefined;
        const bv = b[field] as string | number | undefined;
        if (av === undefined && bv === undefined) return 0;
        if (av === undefined) return 1;
        if (bv === undefined) return -1;
        if (av < bv) return asc ? -1 : 1;
        if (av > bv) return asc ? 1 : -1;
        return 0;
      });
    }

    // Apply limit
    if (this.limitN !== null) {
      rows = rows.slice(0, this.limitN);
    }

    return { data: rows, error: null };
  }
}

// ─── Mock Auth ───────────────────────────────────────────────────────────────

const mockAuth = {
  getUser: async () => ({ data: { user: null }, error: null }),
  getSession: async () => ({ data: { session: null }, error: null }),
  signInWithPassword: async () => ({ data: { user: null }, error: null }),
  // The login page calls signInWithOtp. Demo mode has no mailer, so report a
  // clear error instead of throwing "signInWithOtp is not a function" — demo
  // visitors are meant to use the "直接进入" link.
  signInWithOtp: async () => ({
    data: { user: null, session: null },
    error: {
      name: 'AuthApiError',
      message: '演示模式不发送登录邮件，请使用「直接进入」。',
      status: 501,
    },
  }),
  exchangeCodeForSession: async () => ({
    data: { user: null, session: null },
    error: null,
  }),
  signOut: async () => ({ error: null }),
};

// ─── Mock Channel (for realtime — no-op) ─────────────────────────────────────

const mockChannel = {
  on: () => mockChannel,
  subscribe: () => mockChannel,
  unsubscribe: async () => {},
};

const mockChannels = {
  channel: () => mockChannel,
  removeChannel: () => {},
};

// ─── Create Mock Client ──────────────────────────────────────────────────────

let demoTracesSeeded = false;

export function createMockClient(): unknown {
  // Seed demo traces once on first client creation (only in demo mode)
  if (!demoTracesSeeded) {
    demoTracesSeeded = true;
    // Dynamic import to avoid circular dependency at module load time
    import('./agent/trace').then(({ seedDemoTraces }) => seedDemoTraces()).catch(() => {});
  }
  return {
    from: (table: string) => new MockQueryBuilder(table),
    auth: mockAuth,
    channel: mockChannels.channel,
    channels: mockChannels,
    getChannels: () => [],
    removeChannel: mockChannels.removeChannel,
  };
}
