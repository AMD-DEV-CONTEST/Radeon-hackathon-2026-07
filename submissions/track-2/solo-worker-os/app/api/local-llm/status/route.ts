import { NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * Local LLM health probe.
 *
 * Used by the Settings page to show whether the on-premise AMD Radeon GPU
 * inference endpoint (vLLM / SGLang) is reachable, and which models it is
 * serving. This provides visible evidence that the private deployment is using
 * the configured self-hosted endpoint rather than a commercial LLM API.
 *
 * Safe to call in any provider mode: when AGENT_PROVIDER != 'local' it just
 * reports the current provider and skips the probe.
 */

interface LocalLlmStatus {
  provider: string;
  isLocal: boolean;
  baseUrl: string;
  configuredModel: string;
  reachable: boolean;
  servedModels: string[];
  latencyMs: number | null;
  error: string | null;
}

/** Strip /v1/chat/completions (or any trailing path) to get the serve root. */
function serveRoot(baseUrl: string): string {
  const noChat = baseUrl.replace(/\/v1\/chat\/completions.*$/i, '');
  return noChat.replace(/\/+$/, '');
}

export async function GET() {
  const provider = (process.env.AGENT_PROVIDER ?? 'qwen').toLowerCase();
  const baseUrl = process.env.LOCAL_LLM_BASE_URL ?? 'http://localhost:8000/v1/chat/completions';
  const configuredModel = process.env.LOCAL_LLM_MODEL ?? 'Qwen/Qwen3-4B';

  const status: LocalLlmStatus = {
    provider,
    isLocal: provider === 'local',
    baseUrl,
    configuredModel,
    reachable: false,
    servedModels: [],
    latencyMs: null,
    error: null,
  };

  // Only probe when local is the active provider — otherwise this endpoint
  // is informational (shows what local mode would use).
  if (provider !== 'local') {
    return NextResponse.json(status);
  }

  const modelsUrl = `${serveRoot(baseUrl)}/v1/models`;
  const apiKey = process.env.LOCAL_LLM_API_KEY ?? 'EMPTY';
  const start = Date.now();

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5_000);
    const res = await fetch(modelsUrl, {
      headers: { Authorization: `Bearer ${apiKey}` },
      signal: controller.signal,
    });
    clearTimeout(timeout);

    status.latencyMs = Date.now() - start;

    if (res.ok) {
      status.reachable = true;
      const data = (await res.json()) as { data?: Array<{ id?: string }> };
      status.servedModels = (data?.data ?? [])
        .map((m) => m?.id)
        .filter((id): id is string => typeof id === 'string' && id.length > 0);
    } else {
      status.error = `vLLM/SGLang returned HTTP ${res.status}`;
    }
  } catch (err) {
    status.latencyMs = Date.now() - start;
    status.error =
      err instanceof Error
        ? err.name === 'AbortError'
          ? 'probe timed out (5s) — is vLLM/SGLang running?'
          : err.message
        : String(err);
  }

  return NextResponse.json(status);
}
