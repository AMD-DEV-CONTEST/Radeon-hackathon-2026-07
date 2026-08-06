// ============================================================================
// Simulate a Feishu Event Subscription push to verify the full pipeline:
//   Webhook → decrypt → store → bot_chat_sessions → auto-evaluate → quality_reports
//
// Usage: node scripts/test-feishu-pipeline.mjs
// ============================================================================

const CRYPTO = await import("node:crypto");
const { sha256, randomUUID } = CRYPTO;

const BASE_URL = process.argv[2] || "http://localhost:3000";
const ENCRYPT_KEY = process.env.FEISHU_EVENT_ENCRYPT_KEY || "Ro/vKnH/rpJ8mAUWwgt44zoubHST6+c6AWxbX9GaXBY=";
const VERIFY_TOKEN = process.env.FEISHU_VERIFY_TOKEN || "71aec8c9cbc1dbc60ba5b65b1f28c620";

// ─── Build a realistic im.message.receive_v1 event ───
const now = Date.now();
const eventId = `test_${randomUUID().slice(0, 8)}`;
const chatId = `oc_test_${randomUUID().slice(0, 12)}`;
const senderId = `ou_test_${randomUUID().slice(0, 8)}`;

const messages = [
  "你好，我的订单都三天了还没发货，怎么回事？",
  "页面写着48小时内发货，这都72小时了",
  "能不能帮我查一下物流状态？",
];
const text = messages[Math.floor(Math.random() * messages.length)];

const eventPayload = {
  schema: "2.0",
  header: {
    event_id: eventId,
    event_type: "im.message.receive_v1",
    create_time: String(Math.floor(now / 1000)),
    token: VERIFY_TOKEN,
    app_id: "cli_test",
  },
  event: {
    sender: {
      sender_id: { open_id: senderId, union_id: "on_test", user_id: "u_test" },
      sender_type: "user",
    },
    message: {
      message_id: `om_test_${randomUUID().slice(0, 8)}`,
      root_id: "",
      parent_id: "",
      create_time: String(Math.floor(now / 1000)),
      chat_id: chatId,
      chat_type: "p2p",
      message_type: "text",
      content: JSON.stringify({ text }),
    },
  },
};

const plaintext = JSON.stringify(eventPayload);
console.log("[TEST] Plaintext event:", plaintext.slice(0, 120) + "...");

// ─── Encrypt (AES-256-CBC, matches Feishu's scheme) ───
const keyHash = CRYPTO.createHash("sha256").update(ENCRYPT_KEY).digest();
const iv = CRYPTO.randomBytes(16);
const cipher = CRYPTO.createCipheriv("aes-256-cbc", keyHash, iv);
const encrypted = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
const encryptedBase64 = Buffer.concat([iv, encrypted]).toString("base64");

const body = JSON.stringify({ encrypt: encryptedBase64 });

// ─── Compute signature ───
const timestamp = String(Math.floor(Date.now() / 1000));
const nonce = randomUUID().replace(/-/g, "").slice(0, 16);
const signStr = `${timestamp}${nonce}${ENCRYPT_KEY}${body}`;
const signature = CRYPTO.createHash("sha256").update(signStr).digest("hex");

console.log("[TEST] Chat ID:", chatId);
console.log("[TEST] Sender:", senderId);
console.log("[TEST] Text:", text);
console.log("[TEST] Timestamp:", timestamp, "Nonce:", nonce);
console.log("[TEST] Target:", `${BASE_URL}/api/feishu/event`);
console.log("");

// ─── Send ───
const t0 = Date.now();
const res = await fetch(`${BASE_URL}/api/feishu/event`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-Lark-Request-Timestamp": timestamp,
    "X-Lark-Request-Nonce": nonce,
    "X-Lark-Signature": signature,
  },
  body,
});

const ms = Date.now() - t0;
const resBody = await res.json();
console.log(`[RESPONSE] HTTP ${res.status} in ${ms}ms:`, JSON.stringify(resBody));

// ─── Verify: Check Supabase for the stored session ───
console.log("");
console.log("─────────── Verification ───────────");

// Load env from .env.local
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const envPath = resolve(__dirname, "..", ".env.local");
const envContent = readFileSync(envPath, "utf8");
const env = {};
for (const line of envContent.split("\n")) {
  const m = line.match(/^([A-Z_][A-Z0-9_]*)=(.*)$/);
  if (m) env[m[1]] = m[2].trim();
}

// Check 1: bot_chat_sessions
const { createClient } = await import("@supabase/supabase-js");
const supabase = createClient(
  env.NEXT_PUBLIC_SUPABASE_URL || "https://hrkkkselodznkrolcfwn.supabase.co",
  env.SUPABASE_SERVICE_ROLE_KEY || "",
);

console.log("[CHECK 1] bot_chat_sessions...");
const { data: sessions, error: sErr } = await supabase
  .from("bot_chat_sessions")
  .select("id, conversation, tags, total_messages")
  .eq("external_session_id", chatId)
  .maybeSingle();

if (sErr) {
  console.log("  ERROR:", sErr.message);
} else if (sessions) {
  console.log("  ✅ Session found:", sessions.id);
  console.log("     Conversation:", (sessions.conversation || "").slice(0, 100));
  console.log("     Tags:", sessions.tags);
} else {
  console.log("  ❌ No session found — check Edge Function / Vercel logs");
}

// Check 2: feishu_raw_events
console.log("[CHECK 2] feishu_raw_events...");
const { data: raw, error: rErr } = await supabase
  .from("feishu_raw_events")
  .select("id, event_type")
  .eq("event_id", eventId)
  .maybeSingle();

if (rErr) {
  console.log("  ERROR:", rErr.message);
} else if (raw) {
  console.log("  ✅ Raw event stored:", raw.id, `(type=${raw.event_type})`);
} else {
  console.log("  ⚠️  No raw event found (table may not exist yet)");
}

// Check 3: quality_reports (may take a few seconds for LLM eval)
console.log("[CHECK 3] quality_reports (searching by correlation_id)...");
await new Promise((r) => setTimeout(r, 3000)); // give LLM time

const { data: reports, error: qErr } = await supabase
  .from("quality_reports")
  .select("id, total_score, violations, risk_level, correlation_id")
  .order("created_at", { ascending: false })
  .limit(5);

if (qErr) {
  console.log("  ERROR:", qErr.message);
} else if (reports && reports.length > 0) {
  console.log("  ✅ Quality reports (recent 5):");
  reports.forEach((r) => {
    console.log(`     id=${r.id} score=${r.total_score} risk=${r.risk_level} violations=${r.violations?.length || 0} cid=${(r.correlation_id||'').slice(-20)}`);
  });
} else {
  console.log("  ⚠️  No quality reports found");
}

// Check 4: audit_logs
console.log("[CHECK 4] audit_logs...");
const { data: audits, error: aErr } = await supabase
  .from("audit_logs")
  .select("id, action")
  .eq("resource_id", eventId)
  .maybeSingle();

if (aErr) {
  console.log("  ERROR:", aErr.message);
} else if (audits) {
  console.log("  ✅ Audit log found:", audits.id, `(action=${audits.action})`);
} else {
  console.log("  ⚠️  No audit log found");
}

console.log("");
console.log("─────────── Pipeline test complete ───────────");
supabase.auth.signOut?.();
process.exit(0);
