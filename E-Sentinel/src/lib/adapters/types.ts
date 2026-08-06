// ============================================================================
// PlatformAdapter interface — the contract every platform adapter must fulfill.
// ============================================================================

import type { CanonicalMessage, CanonicalReply, AdapterHealth } from "../types/canonical-message";

export interface PlatformAdapter {
  /** Platform code matching platforms.code in DB */
  readonly platformCode: string;

  /**
   * Phase 1: Verify incoming webhook signature and parse the raw body
   * into a platform-agnostic CanonicalMessage. Throws on invalid signature.
   */
  verifyAndNormalize(
    headers: Headers,
    rawBody: string,
    queryParams: Record<string, string>,
  ): Promise<CanonicalMessage>;

  /**
   * Phase 2: Send a reply back through the platform's API.
   * Returns the platform-assigned message ID on success.
   */
  sendReply(reply: CanonicalReply): Promise<{ success: boolean; messageId?: string }>;

  /**
   * Phase 3: Refresh authentication credentials (OAuth token, etc.).
   * Called by cron job or on 401 response from platform API.
   */
  refreshAuth(): Promise<void>;

  /** Read-only health snapshot for circuit breaker decisions */
  readonly health: AdapterHealth;
}

export type { CanonicalMessage, CanonicalReply, AdapterHealth };
