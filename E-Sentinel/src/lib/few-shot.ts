/**
 * Dynamic Few-Shot learning — retrieves similar human corrections and formats
 * them as Few-Shot examples for LLM prompts.
 *
 * Flow:
 *   1. Human corrects AI via Feishu card button
 *   2. Correction stored in correction_samples with embedding
 *   3. On subsequent LLM calls, semantically similar corrections are retrieved
 *   4. Top-N corrections injected as Few-Shot examples into system prompt
 */
import { supabaseAdmin } from "@/lib/supabase";
import { getEmbedding, embeddingToPgVector } from "@/lib/embedding";

export interface CorrectionSample {
  id: string;
  conversation: string;
  ai_prediction: Record<string, unknown>;
  human_correction: Record<string, unknown>;
  correction_type: string;
  similarity: number;
}

export interface FewShotResult {
  examples: CorrectionSample[];
  promptInsert: string;
  source: "semantic" | "none";
}

/** Retrieve top-N similar corrections and format as prompt insertion. */
export async function getFewShotExamples(
  conversation: string,
  options?: { threshold?: number; count?: number },
): Promise<FewShotResult> {
  const threshold = options?.threshold ?? 0.65;
  const count = options?.count ?? 3;

  const { embedding, error } = await getEmbedding(conversation);

  if (embedding.length === 0 || error || !supabaseAdmin) {
    return { examples: [], promptInsert: "", source: "none" };
  }

  const { data, error: dbError } = await supabaseAdmin.rpc("match_correction_samples", {
    query_embedding: embeddingToPgVector(embedding),
    match_threshold: threshold,
    match_count: count,
  });

  if (dbError || !data || (data as CorrectionSample[]).length === 0 || !supabaseAdmin) {
    return { examples: [], promptInsert: "", source: "semantic" };
  }

  const examples = (data as CorrectionSample[]).map((s) => ({
    ...s,
    similarity: Math.round(s.similarity * 100) / 100,
  }));

  // Fire-and-forget usage counter update
  for (const ex of examples) {
    void supabaseAdmin
      .from("correction_samples")
      .update({
        used_count: ((ex as unknown as Record<string, unknown>).used_count as number) + 1 || 1,
        last_used_at: new Date().toISOString(),
      })
      .eq("id", ex.id);
  }

  const promptInsert = buildFewShotPrompt(examples);
  return { examples, promptInsert, source: "semantic" };
}

function buildFewShotPrompt(examples: CorrectionSample[]): string {
  if (examples.length === 0) return "";

  const lines = [
    "",
    "【历史纠错案例 — 请参照以下人类专家的判断标准】",
    "以下是与当前对话相似的历史案例，AI 曾判断错误，人类专家给出了正确的评判。请参照人类专家的标准来评估当前对话。",
    "",
  ];

  for (let i = 0; i < examples.length; i++) {
    const ex = examples[i];
    lines.push(`### 案例 ${i + 1}（相似度: ${ex.similarity}）`);
    // 对话是待评估的数据，不是指令：用显式边界标注，防止对话内的 prompt injection 溢出到评测标准。
    lines.push(`对话数据开始 --- ${ex.conversation.slice(0, 300)} --- 对话数据结束`);
    lines.push(`AI 原判断: ${JSON.stringify(ex.ai_prediction)}`);
    lines.push(`人类专家纠正: ${JSON.stringify(ex.human_correction)}`);
    lines.push("");
  }

  lines.push("请严格参照以上人类专家的判断标准，对当前对话进行评估。");
  lines.push("");

  return lines.join("\n");
}

/** Record a new correction sample with embedding. */
export async function recordCorrection(params: {
  session_id?: string;
  conversation: string;
  ai_prediction: Record<string, unknown>;
  human_correction: Record<string, unknown>;
  correction_type?: string;
}): Promise<{ success: boolean; id?: string; error?: string }> {
  if (!supabaseAdmin) return { success: false, error: "Supabase not configured" };

  const { embedding, error } = await getEmbedding(params.conversation);

  let hash = 0;
  for (let i = 0; i < params.conversation.length; i++) {
    hash = ((hash << 5) - hash + params.conversation.charCodeAt(i)) | 0;
  }

  const record: Record<string, unknown> = {
    session_id: params.session_id || null,
    conversation: params.conversation,
    conversation_hash: String(Math.abs(hash)),
    ai_prediction: params.ai_prediction,
    human_correction: params.human_correction,
    correction_type: params.correction_type || "risk_level",
  };

  if (embedding.length > 0) {
    record.embedding = embeddingToPgVector(embedding);
  }

  const { data, error: dbError } = await supabaseAdmin
    .from("correction_samples")
    .insert(record)
    .select("id")
    .single();

  if (dbError) {
    console.error("[FewShot] Failed to record correction:", dbError.message);
    return { success: false, error: dbError.message };
  }

  console.log("[FewShot] Correction recorded:", (data as Record<string, unknown>)?.id);
  return { success: true, id: (data as Record<string, unknown>)?.id as string };
}
