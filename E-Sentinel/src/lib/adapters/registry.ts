// ============================================================================
// Platform Adapter Registry — maps platform code → adapter instance.
// Adapters self-register at module load time via registerAdapter().
// ============================================================================

import type { PlatformAdapter } from "./types";

const _adapters = new Map<string, PlatformAdapter>();

export function registerAdapter(adapter: PlatformAdapter): void {
  _adapters.set(adapter.platformCode, adapter);
}

export function getAdapter(code: string): PlatformAdapter | undefined {
  return _adapters.get(code);
}

export function listAdapters(): string[] {
  return Array.from(_adapters.keys());
}
