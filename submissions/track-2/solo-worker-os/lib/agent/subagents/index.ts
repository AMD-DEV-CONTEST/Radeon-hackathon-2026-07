/**
 * Subagent registry — holds all SubagentConfig definitions.
 *
 * The FunctionRouter (Phase 4) queries this registry to:
 *   1. Get all subagent configs for keyword matching (Layer 1)
 *   2. Get subagent by id for system prompt + tool selection
 *   3. Get routing examples for LLM intent classification (Layer 2)
 */

import type { SubagentConfig, SubagentId } from '../types';
import { generalSubagent } from './general';
import { knowledgeRagSubagent } from './knowledge_rag';
import { dataAnalysisSubagent } from './data_analysis';
import { writingAssistantSubagent } from './writing_assistant';
import { quickChatSubagent } from './quick_chat';

// ─── Registry ─────────────────────────────────────────────────────────────────

const ALL_SUBAGENTS: SubagentConfig[] = [
  generalSubagent,
  knowledgeRagSubagent,
  dataAnalysisSubagent,
  writingAssistantSubagent,
  quickChatSubagent,
];

const SUBAGENT_MAP = new Map<SubagentId, SubagentConfig>(
  ALL_SUBAGENTS.map((s) => [s.id, s])
);

/** Get a subagent config by id */
export function getSubagent(id: SubagentId): SubagentConfig {
  const config = SUBAGENT_MAP.get(id);
  if (!config) {
    // Fallback to general if unknown
    return generalSubagent;
  }
  return config;
}

/** Get all subagent configs (for router keyword matching) */
export function getAllSubagents(): SubagentConfig[] {
  return ALL_SUBAGENTS;
}

/** Get all routing examples (for LLM intent classification) */
export function getAllRoutingExamples(): { subagent: SubagentId; examples: string[] }[] {
  return ALL_SUBAGENTS.map((s) => ({
    subagent: s.id,
    examples: s.routingExamples,
  }));
}

/** Get tools for a specific subagent */
export function getSubagentTools(id: SubagentId): string[] {
  return getSubagent(id).tools;
}

/** Check if a subagent is lightweight (skip heavy tools) */
export function isLightweight(id: SubagentId): boolean {
  return getSubagent(id).lightweight ?? false;
}

export { generalSubagent, knowledgeRagSubagent, dataAnalysisSubagent, writingAssistantSubagent, quickChatSubagent };
export type { SubagentConfig, SubagentId } from '../types';
