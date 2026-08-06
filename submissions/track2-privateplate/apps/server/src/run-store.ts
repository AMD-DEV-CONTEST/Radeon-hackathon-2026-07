import { randomUUID } from "node:crypto";
import type {
  AgentEvent,
  ConfirmationRequiredEvent,
  ReplayableAgentEvent
} from "./events.js";

export type StoredRun = {
  runId: string;
  sessionId: string;
  events: ReplayableAgentEvent[];
  status: "running" | "completed" | "failed";
  createdAt: string;
  completedAt: string | null;
};

type EventListener = (event: AgentEvent) => void;

export class AgentRunStore {
  private readonly runs = new Map<string, StoredRun>();
  private readonly listeners = new Map<string, Set<EventListener>>();
  private readonly pendingUiOnly = new Map<
    string,
    { event: ConfirmationRequiredEvent; insertAt: number }
  >();
  private readonly uiOnlyTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private readonly retentionTimers = new Map<string, ReturnType<typeof setTimeout>>();

  create(sessionId: string): StoredRun {
    const run: StoredRun = {
      runId: `run-${randomUUID()}`,
      sessionId,
      events: [],
      status: "running",
      createdAt: new Date().toISOString(),
      completedAt: null
    };
    this.runs.set(run.runId, run);
    return run;
  }

  get(runId: string): StoredRun | null {
    return this.runs.get(runId) ?? null;
  }

  hasRunning(): boolean {
    return [...this.runs.values()].some((run) => run.status === "running");
  }

  append(runId: string, event: ReplayableAgentEvent): void {
    const run = this.runs.get(runId);
    if (!run) {
      throw new Error(`Unknown agent run: ${runId}`);
    }

    run.events.push(event);
    for (const listener of this.listeners.get(runId) ?? []) {
      listener(event);
    }
  }

  publishUiOnly(runId: string, event: ConfirmationRequiredEvent): void {
    const run = this.runs.get(runId);
    if (!run) {
      throw new Error(`Unknown agent run: ${runId}`);
    }

    const listener = this.listeners.get(runId)?.values().next().value;
    if (listener) {
      listener(event);
      return;
    }

    this.pendingUiOnly.set(runId, {
      event,
      insertAt: run.events.length
    });
    const expiresInMs = Math.max(
      0,
      new Date(event.expiresAt).getTime() - Date.now()
    );
    const timer = setTimeout(() => {
      this.pendingUiOnly.delete(runId);
      this.uiOnlyTimers.delete(runId);
    }, expiresInMs);
    timer.unref();
    this.uiOnlyTimers.set(runId, timer);
  }

  takeDeliverySnapshot(runId: string): AgentEvent[] {
    const run = this.runs.get(runId);
    if (!run) {
      throw new Error(`Unknown agent run: ${runId}`);
    }

    const events: AgentEvent[] = [...run.events];
    const uiOnly = this.pendingUiOnly.get(runId);
    if (uiOnly) {
      this.pendingUiOnly.delete(runId);
      const timer = this.uiOnlyTimers.get(runId);
      if (timer) clearTimeout(timer);
      this.uiOnlyTimers.delete(runId);
      events.splice(uiOnly.insertAt, 0, uiOnly.event);
    }
    return events;
  }

  finish(runId: string, status: "completed" | "failed"): void {
    const run = this.runs.get(runId);
    if (!run) {
      throw new Error(`Unknown agent run: ${runId}`);
    }
    run.status = status;
    run.completedAt = new Date().toISOString();
    const timer = setTimeout(() => this.delete(runId), 15 * 60_000);
    timer.unref();
    this.retentionTimers.set(runId, timer);
  }

  subscribe(runId: string, listener: EventListener): () => void {
    if (!this.runs.has(runId)) {
      throw new Error(`Unknown agent run: ${runId}`);
    }
    const runListeners = this.listeners.get(runId) ?? new Set<EventListener>();
    runListeners.add(listener);
    this.listeners.set(runId, runListeners);

    return () => {
      runListeners.delete(listener);
      if (runListeners.size === 0) {
        this.listeners.delete(runId);
      }
    };
  }

  clear(): void {
    for (const timer of this.uiOnlyTimers.values()) clearTimeout(timer);
    for (const timer of this.retentionTimers.values()) clearTimeout(timer);
    this.runs.clear();
    this.listeners.clear();
    this.pendingUiOnly.clear();
    this.uiOnlyTimers.clear();
    this.retentionTimers.clear();
  }

  delete(runId: string): void {
    const uiOnlyTimer = this.uiOnlyTimers.get(runId);
    if (uiOnlyTimer) clearTimeout(uiOnlyTimer);
    const retentionTimer = this.retentionTimers.get(runId);
    if (retentionTimer) clearTimeout(retentionTimer);
    this.runs.delete(runId);
    this.listeners.delete(runId);
    this.pendingUiOnly.delete(runId);
    this.uiOnlyTimers.delete(runId);
    this.retentionTimers.delete(runId);
  }
}
