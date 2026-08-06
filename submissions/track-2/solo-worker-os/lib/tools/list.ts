/**
 * Canonical tool list — exported separately from index.ts to avoid
 * barrel-file resolution issues in non-Next.js contexts (e.g. MCP server).
 */

import type { ToolConfig } from './types';

import { createProjectTool } from './handlers/create_project';
import { updateProjectStatusTool } from './handlers/update_project_status';
import { generateContractTool } from './handlers/generate_contract';
import { generateInvoiceTool } from './handlers/generate_invoice';
import { recordPaymentTool } from './handlers/record_payment';
import { exportMonthlyReportTool } from './handlers/export_monthly_report';
import { generateFollowupMessageTool } from './handlers/generate_followup_message';
import { searchKnowledgeBaseTool } from './handlers/search_knowledge_base';
import { getExchangeRatesTool } from './handlers/get_exchange_rates';
import { getPricingBenchmarkTool } from './handlers/get_pricing_benchmark';
import { analyzeBusinessDataTool } from './handlers/analyze_business_data';
import { getUpcomingDeadlinesTool } from './handlers/get_upcoming_deadlines';
import { archiveDeliverableTool } from './handlers/archive_deliverable';
import { browserAutomateTool } from './handlers/browser_automate';

export const ALL_TOOLS: ToolConfig[] = [
  createProjectTool,
  updateProjectStatusTool,
  generateContractTool,
  generateInvoiceTool,
  recordPaymentTool,
  exportMonthlyReportTool,
  generateFollowupMessageTool,
  searchKnowledgeBaseTool,
  getExchangeRatesTool,
  getPricingBenchmarkTool,
  analyzeBusinessDataTool,
  getUpcomingDeadlinesTool,
  archiveDeliverableTool,
  browserAutomateTool,
];
