import type { Recipe } from './types';

/**
 * Pre-built recipe definitions.
 *
 * Each recipe represents a real-world business workflow that a solo worker
 * performs repeatedly. The recipes chain existing tools into a single
 * one-shot execution, turning "tools" into "delivered results".
 */

export const RECIPES: Recipe[] = [
  // ─── 1. New Client Onboarding ──────────────────────────────────────────
  {
    id: 'new-client-onboarding',
    name: '新客户签约交付包',
    description: '从客户信息到合同、发票、项目跟踪，一步到位完成签约流程',
    icon: 'handshake',
    category: 'sales',
    inputs: [
      { name: 'client_name', label: '客户名称', type: 'string', required: true, placeholder: '张明' },
      { name: 'project_type', label: '项目类型', type: 'string', required: true, placeholder: '企业官网重构与上线' },
      { name: 'budget', label: '预算（元）', type: 'number', required: true, placeholder: '35000' },
      { name: 'deadline', label: '截止日期', type: 'date', required: true },
      { name: 'currency', label: '币种', type: 'select', required: false, default: 'CNY', options: ['CNY', 'USD'] },
    ],
    steps: [
      {
        tool: 'create_project',
        label: '创建项目',
        inputTemplate: {
          client_name: '${client_name}',
          project_type: '${project_type}',
          budget: '${budget}',
          currency: '${currency}',
          deadline: '${deadline}',
        },
      },
      {
        tool: 'generate_contract',
        label: '生成服务合同',
        inputTemplate: {
          client_name: '${client_name}',
          project_type: '${project_type}',
        },
      },
    ],
    deliverables: ['项目档案', '服务合同'],
    estimatedTimeSaved: 15,
  },

  // ─── 2. Invoice & Payment Collection ────────────────────────────────────
  {
    id: 'invoice-payment-cycle',
    name: '开票收款跟进包',
    description: '自动开票、记录收款、更新项目状态，完成完整财务闭环',
    icon: 'receipt',
    category: 'finance',
    inputs: [
      { name: 'client_name', label: '客户名称', type: 'string', required: true, placeholder: '王浩' },
      { name: 'project_type', label: '项目类型（可选，用于消歧）', type: 'string', required: false },
      { name: 'due_date', label: '付款截止日', type: 'date', required: false },
    ],
    steps: [
      {
        tool: 'generate_invoice',
        label: '生成发票',
        inputTemplate: {
          client_name: '${client_name}',
          project_type: '${project_type}',
          due_date: '${due_date}',
        },
      },
      {
        tool: 'generate_followup_message',
        label: '生成付款跟进消息',
        inputTemplate: {
          client_name: '${client_name}',
          project_type: '${project_type}',
          tone: 'polite',
        },
      },
    ],
    deliverables: ['发票', '付款跟进消息'],
    estimatedTimeSaved: 10,
  },

  // ─── 3. Project Delivery & Archive ──────────────────────────────────────
  {
    id: 'delivery-archive',
    name: '项目交付归档包',
    description: '更新交付状态、归档交付物、生成交付确认书，完成项目收尾',
    icon: 'archive',
    category: 'delivery',
    inputs: [
      { name: 'client_name', label: '客户名称', type: 'string', required: true, placeholder: '刘洋' },
      { name: 'project_type', label: '项目类型（可选）', type: 'string', required: false },
      { name: 'deliverable_title', label: '交付物名称', type: 'string', required: true, placeholder: '产品宣传视频成片' },
      { name: 'deliverable_url', label: '交付物链接', type: 'string', required: false, placeholder: 'https://...' },
    ],
    steps: [
      {
        tool: 'update_project_status',
        label: '更新项目状态为已交付',
        inputTemplate: {
          client_name: '${client_name}',
          project_type: '${project_type}',
          status: 'delivered',
        },
      },
      {
        tool: 'archive_deliverable',
        label: '归档交付物',
        inputTemplate: {
          client_name: '${client_name}',
          project_type: '${project_type}',
          title: '${deliverable_title}',
          url: '${deliverable_url}',
          type: 'final_delivery',
        },
      },
    ],
    deliverables: ['交付状态更新', '交付物归档记录'],
    estimatedTimeSaved: 8,
  },

  // ─── 4. Monthly Business Report ─────────────────────────────────────────
  {
    id: 'monthly-report',
    name: '月度经营报表包',
    description: '一键生成本月收入统计、项目完成情况、客户分布分析',
    icon: 'chart',
    category: 'management',
    inputs: [
      { name: 'month', label: '月份', type: 'string', required: false, placeholder: '2026-07', default: 'current' },
    ],
    steps: [
      {
        tool: 'export_monthly_report',
        label: '生成月度报表',
        inputTemplate: {
          month: '${month}',
        },
      },
      {
        tool: 'analyze_business_data',
        label: '分析经营数据',
        inputTemplate: {
          analysis_type: 'monthly_summary',
        },
      },
    ],
    deliverables: ['月度报表', '经营分析'],
    estimatedTimeSaved: 30,
  },

  // ─── 5. Full Lifecycle — Start to Payment ───────────────────────────────
  {
    id: 'full-lifecycle',
    name: '全流程闭环包',
    description: '从建项目到收款，完整商业闭环一步执行：建项目→合同→交付→开票→收款',
    icon: 'rocket',
    category: 'sales',
    inputs: [
      { name: 'client_name', label: '客户名称', type: 'string', required: true, placeholder: '赵雪' },
      { name: 'project_type', label: '项目类型', type: 'string', required: true, placeholder: '品牌发布会演示设计' },
      { name: 'budget', label: '预算（元）', type: 'number', required: true, placeholder: '5000' },
      { name: 'deadline', label: '截止日期', type: 'date', required: true },
      { name: 'payment_method', label: '付款方式', type: 'select', required: false, default: 'wechat', options: ['wechat', 'alipay', 'bank_transfer', 'cash'] },
    ],
    steps: [
      {
        tool: 'create_project',
        label: '创建项目',
        inputTemplate: {
          client_name: '${client_name}',
          project_type: '${project_type}',
          budget: '${budget}',
          deadline: '${deadline}',
        },
      },
      {
        tool: 'generate_contract',
        label: '生成合同',
        inputTemplate: {
          client_name: '${client_name}',
          project_type: '${project_type}',
        },
      },
      {
        tool: 'update_project_status',
        label: '标记已交付',
        inputTemplate: {
          client_name: '${client_name}',
          project_type: '${project_type}',
          status: 'delivered',
        },
      },
      {
        tool: 'generate_invoice',
        label: '生成发票',
        inputTemplate: {
          client_name: '${client_name}',
          project_type: '${project_type}',
        },
      },
      {
        tool: 'record_payment',
        label: '记录收款',
        inputTemplate: {
          client_name: '${client_name}',
          project_type: '${project_type}',
          method: '${payment_method}',
        },
      },
    ],
    deliverables: ['项目档案', '服务合同', '发票', '收款记录'],
    estimatedTimeSaved: 25,
  },
];
