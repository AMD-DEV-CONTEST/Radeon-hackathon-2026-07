// ============================================================================
// Per-platform Circuit Breaker — stateful open/half-open/closed pattern.
// Tracks consecutive failures and opens the circuit when the error rate
// exceeds the configured threshold. Supports half-open probing for recovery.
// ============================================================================

import type { AdapterHealth } from "../types/canonical-message";

type CircuitState = "closed" | "open" | "half-open";

interface CircuitConfig {
  errorRateThreshold: number;
  cooldownMs: number;
  windowSize: number;
}

const DEFAULT_CONFIG: CircuitConfig = {
  errorRateThreshold: 0.05, // 5% error rate triggers open
  cooldownMs: 300_000,      // 5 minute cooldown
  windowSize: 100,           // rolling window of last 100 requests
};

export class CircuitBreaker {
  private state: CircuitState = "closed";
  private lastTransitionAt: number = Date.now();
  private results: Array<{ success: boolean; latencyMs: number }> = [];

  constructor(private config: Partial<CircuitConfig> = {}) {}

  private get cfg(): CircuitConfig {
    return { ...DEFAULT_CONFIG, ...this.config };
  }

  /** Record the outcome of a request and update circuit state */
  record(success: boolean, latencyMs: number): void {
    this.results.push({ success, latencyMs });
    if (this.results.length > this.cfg.windowSize) {
      this.results.shift();
    }

    const windowResults = this.results;
    const errorRate = windowResults.filter((r) => !r.success).length / windowResults.length;

    if (this.state === "closed" && errorRate > this.cfg.errorRateThreshold) {
      this.state = "open";
      this.lastTransitionAt = Date.now();
    } else if (this.state === "half-open" && errorRate <= this.cfg.errorRateThreshold) {
      this.state = "closed";
      this.lastTransitionAt = Date.now();
    }
  }

  /** Check if the circuit allows requests through */
  allowRequest(): boolean {
    if (this.state === "closed") return true;

    if (this.state === "open") {
      const elapsed = Date.now() - this.lastTransitionAt;
      if (elapsed >= this.cfg.cooldownMs) {
        this.state = "half-open";
        this.lastTransitionAt = Date.now();
        return true; // allow one probe request
      }
      return false;
    }

    // half-open: allow probes
    return true;
  }

  /** Manually force the circuit closed (admin override) */
  reset(): void {
    this.state = "closed";
    this.lastTransitionAt = Date.now();
    this.results = [];
  }

  get health(): AdapterHealth {
    const avgLatencyMs = this.results.length > 0
      ? this.results.reduce((s, r) => s + r.latencyMs, 0) / this.results.length
      : 0;

    const errorRate = this.results.length > 0
      ? this.results.filter((r) => !r.success).length / this.results.length
      : 0;

    return {
      avgLatencyMs,
      errorRate,
      isCircuitOpen: this.state === "open",
      lastTransitionAt: new Date(this.lastTransitionAt).toISOString(),
    };
  }
}
