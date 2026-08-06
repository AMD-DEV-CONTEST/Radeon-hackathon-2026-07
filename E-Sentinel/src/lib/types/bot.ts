// ============================================================================
// Shared TypeScript interfaces for bot operations
// ============================================================================

// ── Platform ────────────────────────────────────────────────────────────────
export interface Platform {
  id: string;
  name: string;
  code: string;
  is_active: boolean;
  bot_type: "third_party" | "native" | "hybrid";
  api_endpoint?: string | null;
  created_at: string;
}

// ── Bot Instance ─────────────────────────────────────────────────────────────
export type BotPlatform = "feishu" | "taobao" | "tmall" | "jd" | "pdd" | "web";

export interface BotWorkingHours {
  start: string;
  end: string;
  timezone?: string;
}

export interface Bot {
  id: string;
  tenant_id?: string | null;
  name: string;
  avatar?: string | null;
  welcome_message: string;
  prompt_id?: string | null;
  model_config_id?: string | null;
  platform: BotPlatform;
  working_hours: BotWorkingHours;
  transfer_keywords: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
  // Joined fields
  prompt_name?: string;
  model_name?: string;
}

// ── Bot Config ──────────────────────────────────────────────────────────────
export type ConfigType = "pre_sale" | "post_sale";
export type ConfigStatus = "draft" | "active" | "archived";

export interface BotConfig {
  id: string;
  platform_id: string;
  config_type: ConfigType;
  config_key: string;
  config_value: Record<string, unknown>;
  version: number;
  status: ConfigStatus;
  updated_by?: string | null;
  change_summary?: string | null;
  effect_metrics?: Record<string, unknown> | null;
  source_type?: string | null;
  created_at: string;
  updated_at: string;
}

// ── Knowledge Entry ─────────────────────────────────────────────────────────
export type KnowledgeCategory = "product" | "faq" | "after_sales_policy" | "campaign" | "greeting";
export type KnowledgeStatus = "draft" | "published" | "archived";
export type KnowledgeTone = "professional" | "friendly" | "concise" | "";

export interface KnowledgeEntry {
  id: string;
  category: KnowledgeCategory;
  platform_id?: string | null;
  title: string;
  content: string;
  keywords: string[];
  tags: string[];
  tone?: KnowledgeTone;
  priority: number;
  status: KnowledgeStatus;
  source?: string | null;
  updated_by?: string | null;
  version: number;
  hit_count?: number;
  last_hit_at?: string | null;
  gap_source_count?: number;
  effect_metrics?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

// ── Bot Chat Session ────────────────────────────────────────────────────────
export type SessionType = "pre_sale" | "post_sale";
export type InquiryResult = "converted" | "lost" | "pending";
export type SatisfactionRating = "good" | "neutral" | "bad";

export interface BotChatSession {
  id: string;
  platform_id: string;
  session_type: SessionType;
  external_session_id?: string | null;
  customer_id?: string | null;
  bot_handled: boolean;
  transfer_reason?: string | null;
  is_inquiry: boolean;
  inquiry_result?: InquiryResult | null;
  sentiment_score?: number | null;
  satisfaction?: SatisfactionRating | null;
  total_messages: number;
  first_response_ms?: number | null;
  resolution_ms?: number | null;
  tags: string[];
  conversation: string;
  correlation_id: string;
  created_at: string;
  // Joined
  platform_name?: string;
}

// ── Optimization Task ───────────────────────────────────────────────────────
export type OptTaskSource = "chat_inspection" | "inquiry_loss" | "satisfaction" | "campaign" | "manual" | "knowledge_gap";
export type OptTaskStatus = "open" | "in_progress" | "resolved" | "wont_fix";
export type OptTaskPriority = "low" | "medium" | "high" | "critical";

export interface OptimizationTask {
  id: string;
  source: OptTaskSource;
  category: string;
  title: string;
  description: string;
  priority: OptTaskPriority;
  status: OptTaskStatus;
  platform_id?: string | null;
  related_chat_id?: string | null;
  related_knowledge_id?: string | null;
  assigned_to?: string | null;
  resolution?: string | null;
  impact_estimate?: string | null;
  created_by?: string | null;
  created_at: string;
  resolved_at?: string | null;
}

// ── Robot Report ────────────────────────────────────────────────────────────
export type ReportType = "daily" | "weekly" | "monthly";

export interface RobotReport {
  id: string;
  report_type: ReportType;
  period_start: string;
  period_end: string;
  platform_id?: string | null;
  summary_md: string;
  metrics: Record<string, unknown>;
  optimization_plan?: string | null;
  industry_compare?: Record<string, unknown> | null;
  generated_by: string;
  created_at: string;
}

// ── Industry Benchmark ──────────────────────────────────────────────────────
export interface IndustryBenchmark {
  id: string;
  metric_name: string;
  industry_avg: number;
  industry_top?: number | null;
  category?: string | null;
  period: string;
}

// ── Knowledge Update Log ────────────────────────────────────────────────────
export type UpdateLogType = "create" | "update" | "publish" | "archive" | "batch_import";

export interface KnowledgeUpdateLog {
  id: string;
  knowledge_id?: string | null;
  update_type: UpdateLogType;
  field_changed?: string | null;
  old_value?: string | null;
  new_value?: string | null;
  updated_by?: string | null;
  correlation_id: string;
  created_at: string;
}

// ── LLM Inspection Results ──────────────────────────────────────────────────
export interface ChatIssue {
  category: string;
  severity: "minor" | "major" | "critical";
  description: string;
  source_quote: string;
}

export interface ChatSuggestion {
  type: "script" | "knowledge" | "logic" | "policy";
  title: string;
  detail: string;
  expected_impact: string;
}

export interface InspectResult {
  session_id: string;
  issues: ChatIssue[];
  suggestions: ChatSuggestion[];
  quality_label: "good" | "needs_improvement" | "problematic";
  independent_rate_impact: "positive" | "neutral" | "negative";
}

// ── Cluster Result ──────────────────────────────────────────────────────────
export interface TopicCluster {
  topic: string;
  count: number;
  examples: string[];
  suggestion: string;
}

// ── Chat Stats ──────────────────────────────────────────────────────────────
export interface ChatStats {
  total_sessions: number;
  bot_handled_rate: number;
  /** @deprecated Same as bot_handled_rate — kept for backward compatibility */
  independent_reception_rate?: number;
  avg_sentiment: number;
  satisfaction_distribution: { good: number; neutral: number; bad: number };
  transfer_rate: number;
  top_issue_categories: { category: string; count: number }[];
  pending_review_count: number;
  pending_breakdown: { bad: number; lost: number; high_risk: number };
}
