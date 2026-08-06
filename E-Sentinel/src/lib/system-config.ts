// System runtime configuration reader.
// Reads from system_configs DB table with fallback to built-in defaults.
// Avoids hardcoded thresholds in business logic — ops can adjust without redeploy.

import { supabaseAdmin } from "./supabase";

const DEFAULT_VALUES: Record<string, string> = {
  auto_publish_threshold: "0.95",
  auto_publish_max_change_length: "50",
  feishu_timeout_ms: "10000",
  feishu_retry_count: "3",
  feishu_night_window_start: "22",
  feishu_night_window_end: "8",
  llm_rate_limit_per_minute: "30",
  llm_cache_ttl_hours: "24",
  llm_max_retries: "3",
  knowledge_gap_similarity_threshold: "0.15",
  qa_kappa_alert_threshold: "0.4",
  compliance_auto_block_threshold: "2",
  dedup_window_days: "7",
};

// In-memory cache to avoid DB calls on every request
let _cache: Record<string, string> | null = null;
let _cacheAt = 0;
const CACHE_TTL = 60000; // 60 seconds

async function loadAll(): Promise<Record<string, string>> {
  const now = Date.now();
  if (_cache && now - _cacheAt < CACHE_TTL) return _cache;

  if (!supabaseAdmin) {
    return { ...DEFAULT_VALUES };
  }

  try {
    const { data } = await supabaseAdmin
      .from("system_configs")
      .select("config_key, config_value");

    if (data && data.length > 0) {
      const map: Record<string, string> = { ...DEFAULT_VALUES };
      for (const row of data as Array<{ config_key: string; config_value: string }>) {
        map[row.config_key] = row.config_value;
      }
      _cache = map;
      _cacheAt = now;
      return map;
    }
  } catch {
    // Table may not exist yet — use defaults
  }

  _cache = { ...DEFAULT_VALUES };
  _cacheAt = now;
  return _cache;
}

export async function getConfigNumber(key: string, fallback?: number): Promise<number> {
  const all = await loadAll();
  const raw = all[key];
  if (raw === undefined) return fallback ?? 0;
  const n = Number(raw);
  return isNaN(n) ? (fallback ?? 0) : n;
}

export async function getConfigString(key: string, fallback?: string): Promise<string> {
  const all = await loadAll();
  return all[key] ?? fallback ?? "";
}

export async function getConfigBoolean(key: string, fallback?: boolean): Promise<boolean> {
  const all = await loadAll();
  const raw = all[key];
  if (raw === undefined) return fallback ?? false;
  return raw === "true";
}

/** Write a config value to the database (upsert) */
export async function setConfigString(key: string, value: string): Promise<boolean> {
  if (!supabaseAdmin) return false;

  try {
    const { error } = await supabaseAdmin
      .from("system_configs")
      .upsert({ config_key: key, config_value: value, updated_at: new Date().toISOString() }, { onConflict: "config_key" });

    if (error) {
      console.error("[system-config] Upsert error:", error.message);
      return false;
    }

    invalidateConfigCache();
    return true;
  } catch (err) {
    console.error("[system-config] Write error:", String(err).slice(0, 100));
    return false;
  }
}

/** Invalidate the cache — call after updating config via API */
export function invalidateConfigCache(): void {
  _cache = null;
  _cacheAt = 0;
}
