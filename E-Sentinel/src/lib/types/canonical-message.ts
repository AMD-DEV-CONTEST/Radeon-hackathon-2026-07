// ============================================================================
// Canonical Message Model — platform-agnostic message representation.
// Every adapter must convert platform-specific payloads into CanonicalMessage.
// reply-router consumes CanonicalReply to dispatch via the correct adapter.
// ============================================================================

/** Platform-agnostic inbound message — what every adapter must produce */
export interface CanonicalMessage {
  /** Unique message ID from the source platform (used for idempotency) */
  platform_message_id: string;
  /** Platform code matching platforms.code in DB: "feishu" | "tmall" | "jd" | ... */
  platform_code: string;
  /** Session-scoped identifier for grouping messages into conversations */
  session_id: string;
  /** End-user identifier on the platform */
  customer_id: string;
  /** Normalized message text regardless of original format (image→"[图片]") */
  content: string;
  /** Original message type from the platform: "text" | "image" | "file" | "mixed" | ... */
  message_type: string;
  /** ISO 8601 timestamp from the source platform */
  timestamp: string;
  /** Opaque metadata the adapter needs for reply routing (chat_id, seller_nick, etc.) */
  reply_context: Record<string, unknown>;
}

/** Platform-agnostic outbound reply — what reply-router consumes */
export interface CanonicalReply {
  /** The canonical message this reply corresponds to */
  in_reply_to: CanonicalMessage;
  /** Reply text content */
  content: string;
  /** Reply type */
  reply_type: "text" | "card" | "image";
  /** Optional Feishu-compatible card payload for interactive replies */
  card?: Record<string, unknown>;
}

/** Platform adapter health snapshot — used by circuit breaker */
export interface AdapterHealth {
  /** Rolling average latency in milliseconds */
  avgLatencyMs: number;
  /** Error rate over the observation window (0-1) */
  errorRate: number;
  /** Whether the circuit breaker is currently open (blocking requests) */
  isCircuitOpen: boolean;
  /** Timestamp of the last state transition */
  lastTransitionAt: string;
}
