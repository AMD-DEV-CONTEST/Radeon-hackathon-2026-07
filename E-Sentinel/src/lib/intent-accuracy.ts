// Intent accuracy tracking — monitors recognition accuracy against 99.8% target.
// Auto-alerts via Feishu when accuracy drops below 99%.

import { supabaseAdmin } from "./supabase";
import { sendFeishuNotification } from "./feishu";

const TARGET_ACCURACY = 0.998;  // 99.8%
const ALERT_THRESHOLD = 0.99;   // 99% — alert if below this

export interface IntentAccuracySnapshot {
  total: number;
  correct: number;
  incorrect: number;
  accuracy: number;
  coverage_rate: number | null;
  target_met: boolean;
}

export async function recordIntentAccuracy(params: {
  platform_id?: string | null;
  total_recognitions: number;
  correct_recognitions: number;
  incorrect_recognitions: number;
  coverage_rate?: number | null;
  bad_case_ids?: string[];
  notes?: string;
}): Promise<IntentAccuracySnapshot> {
  const total = params.total_recognitions;
  const correct = params.correct_recognitions;
  const incorrect = params.incorrect_recognitions;
  const accuracy = total > 0 ? correct / total : 0;
  const targetMet = accuracy >= TARGET_ACCURACY;
  const belowAlert = accuracy < ALERT_THRESHOLD;

  const snapshot: IntentAccuracySnapshot = {
    total,
    correct,
    incorrect,
    accuracy,
    coverage_rate: params.coverage_rate || null,
    target_met: targetMet,
  };

  if (!supabaseAdmin) return snapshot;

  const today = new Date().toISOString().split("T")[0];
  const { data: existing } = await supabaseAdmin
    .from("intent_accuracy_logs")
    .select("id, total_recognitions, correct_recognitions, incorrect_recognitions")
    .eq("period_date", today)
    .eq("platform_id", params.platform_id || null)
    .single();

  if (existing) {
    // Update — accumulate counts
    await supabaseAdmin
      .from("intent_accuracy_logs")
      .update({
        total_recognitions: Number(existing.total_recognitions) + total,
        correct_recognitions: Number(existing.correct_recognitions) + correct,
        incorrect_recognitions: Number(existing.incorrect_recognitions) + incorrect,
        accuracy: (Number(existing.correct_recognitions) + correct) / (Number(existing.total_recognitions) + total),
        target_met: targetMet,
      })
      .eq("id", existing.id);
  } else {
    await supabaseAdmin.from("intent_accuracy_logs").insert({
      platform_id: params.platform_id || null,
      period_date: today,
      total_recognitions: total,
      correct_recognitions: correct,
      incorrect_recognitions: incorrect,
      accuracy,
      coverage_rate: params.coverage_rate || null,
      target_met: targetMet,
      bad_case_ids: params.bad_case_ids || [],
      notes: params.notes || null,
    });
  }

  // Alert if below 99% — uses 4-level Feishu notification routing
  if (belowAlert) {
    sendFeishuNotification({
      header: {
        title: { tag: "plain_text", content: `⚠️ 意图识别准确率告警 — ${(accuracy * 100).toFixed(2)}%` },
        template: "orange",
      },
      elements: [
        {
          tag: "div",
          text: {
            tag: "lark_md",
            content: `**当前准确率：** ${(accuracy * 100).toFixed(2)}%\n**目标：** ≥99.8%\n**告警线：** 99%\n**今日识别总数：** ${total}\n**错误数：** ${incorrect}\n\n请检查 Bad Case 并启动优化流程。`,
          },
        },
      ],
    }).catch(() => {});
  }

  return snapshot;
}

export async function getIntentAccuracyHistory(days: number = 30): Promise<Array<Record<string, unknown>>> {
  if (!supabaseAdmin) return [];

  const cutoff = new Date(Date.now() - days * 86400000).toISOString().split("T")[0];
  try {
    const { data } = await supabaseAdmin
      .from("intent_accuracy_logs")
      .select("*")
      .gte("period_date", cutoff)
      .order("period_date", { ascending: false });

    return (data || []) as Array<Record<string, unknown>>;
  } catch {
    return []; // Table may not exist yet
  }
}

export async function getIntentAccuracyLatest(): Promise<IntentAccuracySnapshot & { period_date: string | null; is_today: boolean }> {
  const fallback = { total: 0, correct: 0, incorrect: 0, accuracy: 0, coverage_rate: null, target_met: false, period_date: null, is_today: false };
  if (!supabaseAdmin) return fallback;

  const today = new Date().toISOString().split("T")[0];
  try {
    // Aggregate across all platforms for today
    const { data } = await supabaseAdmin
      .from("intent_accuracy_logs")
      .select("total_recognitions, correct_recognitions, incorrect_recognitions, accuracy, coverage_rate, target_met, period_date")
      .eq("period_date", today);

    if (!data || data.length === 0) {
      // No data today — fall back to most recent date
      const recent = await getMostRecentDate();
      if (!recent) return fallback;
      const { data: recentData } = await supabaseAdmin
        .from("intent_accuracy_logs")
        .select("total_recognitions, correct_recognitions, incorrect_recognitions, accuracy, coverage_rate, target_met, period_date")
        .eq("period_date", recent);
      if (!recentData || recentData.length === 0) return fallback;
      const total = recentData.reduce((s, r) => s + Number(r.total_recognitions), 0);
      const correct = recentData.reduce((s, r) => s + Number(r.correct_recognitions), 0);
      const incorrect = recentData.reduce((s, r) => s + Number(r.incorrect_recognitions), 0);
      return {
        total, correct, incorrect,
        accuracy: total > 0 ? correct / total : 0,
        coverage_rate: recentData[0].coverage_rate ? Number(recentData[0].coverage_rate) : null,
        target_met: total > 0 ? (correct / total) >= TARGET_ACCURACY : false,
        period_date: recent,
        is_today: false,
      };
    }

    const total = data.reduce((s, r) => s + Number(r.total_recognitions), 0);
    const correct = data.reduce((s, r) => s + Number(r.correct_recognitions), 0);
    const incorrect = data.reduce((s, r) => s + Number(r.incorrect_recognitions), 0);
    return {
      total, correct, incorrect,
      accuracy: total > 0 ? correct / total : 0,
      coverage_rate: data[0].coverage_rate ? Number(data[0].coverage_rate) : null,
      target_met: total > 0 ? (correct / total) >= TARGET_ACCURACY : false,
      period_date: today,
      is_today: true,
    };
  } catch {
    return fallback;
  }
}

export async function getMostRecentDate(): Promise<string | null> {
  if (!supabaseAdmin) return null;
  try {
    const { data } = await supabaseAdmin
      .from("intent_accuracy_logs")
      .select("period_date")
      .order("period_date", { ascending: false })
      .limit(1)
      .maybeSingle();
    return data?.period_date || null;
  } catch {
    return null;
  }
}
