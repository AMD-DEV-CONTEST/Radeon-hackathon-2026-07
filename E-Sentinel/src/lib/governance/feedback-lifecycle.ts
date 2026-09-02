import { createHash } from "node:crypto";

export const FEEDBACK_STATUSES = [
  "captured", "triaged", "accepted", "rejected", "change_drafted",
  "regression_running", "approved", "released", "verified",
] as const;
export type FeedbackStatus = typeof FEEDBACK_STATUSES[number];

export const FEEDBACK_REASON_CODES = [
  "RULE_MISSING", "RULE_CONFLICT", "RETRIEVAL_MISS", "PROMPT_DEFECT",
  "MODEL_JUDGMENT_ERROR", "EVIDENCE_EXTRACTION_ERROR", "LABEL_DISPUTE", "DATA_QUALITY",
] as const;
export type FeedbackReasonCode = typeof FEEDBACK_REASON_CODES[number];

export interface FeedbackRecord {
  feedbackId: string;
  sourceTraceId: string;
  status: FeedbackStatus;
  owner: string;
  reasonCode?: FeedbackReasonCode;
  rejectionReason?: string;
  linkedDatasetItems: string[];
  regressionPassed: boolean;
  approvedBy?: string;
  releaseId?: string;
  updatedAt: string;
}

const transitions: Record<FeedbackStatus, FeedbackStatus[]> = {
  captured: ["triaged"], triaged: ["accepted", "rejected"], accepted: ["change_drafted"],
  rejected: [], change_drafted: ["regression_running"], regression_running: ["approved"],
  approved: ["released"], released: ["verified"], verified: [],
};

export function transitionFeedback(record: FeedbackRecord, next: FeedbackStatus, actor: string, now = new Date().toISOString()): FeedbackRecord {
  if (!actor.trim()) throw new Error("actor is required");
  if (!transitions[record.status].includes(next)) throw new Error(`invalid feedback transition: ${record.status} -> ${next}`);
  if (next === "accepted" && !record.reasonCode) throw new Error("accepted feedback requires one reasonCode");
  if (next === "rejected" && !record.rejectionReason?.trim()) throw new Error("rejected feedback requires rejectionReason");
  if (next === "approved" && (!record.regressionPassed || record.linkedDatasetItems.length === 0)) throw new Error("approved feedback requires a passing regression and linked dataset items");
  if (next === "released" && !record.approvedBy) throw new Error("released feedback requires an approver");
  if (next === "verified" && !record.releaseId) throw new Error("verified feedback requires a releaseId");
  return { ...record, status: next, owner: actor, updatedAt: now };
}

export interface ReleaseManifestInput {
  releaseId: string;
  commitSha: string;
  deploymentId: string;
  model: string;
  promptVersion: string;
  ruleSetVersion: string;
  datasetVersion: string;
  schemaVersion: string;
  evaluationReport: string;
  regressionPassed: boolean;
  approvedBy: string;
  releasedAt: string;
}

export interface ReleaseManifest extends ReleaseManifestInput { integrityHash: string; }

function canonicalize(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${canonicalize(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function createReleaseManifest(input: ReleaseManifestInput): ReleaseManifest {
  const required = Object.entries(input).filter(([, value]) => typeof value === "string" && !value.trim());
  if (required.length) throw new Error(`manifest requires ${required.map(([key]) => key).join(", ")}`);
  if (!input.regressionPassed) throw new Error("manifest requires a passing regression");
  if (!/^[0-9a-f]{7,64}$/i.test(input.commitSha)) throw new Error("manifest commitSha must be a git SHA");
  return { ...input, integrityHash: createHash("sha256").update(canonicalize(input)).digest("hex") };
}

export function verifyReleaseManifest(manifest: ReleaseManifest): boolean {
  const { integrityHash, ...input } = manifest;
  try { return createReleaseManifest(input).integrityHash === integrityHash; } catch { return false; }
}
