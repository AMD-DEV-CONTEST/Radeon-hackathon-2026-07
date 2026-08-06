import {
  PrivatePlateAgent,
  type AgentModelProvider,
  type AgentState,
  type AgentTurnResult,
  type PrivatePlateAgentCore
} from "@privateplate/agent-runtime";
import type { PrivatePlateDomain } from "@privateplate/domain";

type SessionRecord = {
  agent: PrivatePlateAgentCore;
  tail: Promise<void>;
  accepting: boolean;
};

export class AgentSessionManager {
  private readonly sessions = new Map<string, SessionRecord>();
  private readonly clears = new Map<string, Promise<void>>();

  constructor(
    private readonly domain: PrivatePlateDomain,
    private readonly provider: AgentModelProvider
  ) {
    if (!provider) {
      throw new Error(
        "AgentSessionManager requires a non-null AgentModelProvider."
      );
    }
  }

  run(
    sessionId: string,
    userText: string,
    dinerIds?: string[]
  ): Promise<AgentTurnResult> {
    return this.enqueue(sessionId, async (agent) => {
      if (dinerIds) {
        const selection = agent.selectDiners(dinerIds);
        if (!selection.ok) {
          throw new SessionInputError(selection.message);
        }
      }
      // Chip selection seeds state.dinerIds, but must not lock tool args.
      // Otherwise conversation cannot revise members (Scene 4 / ppb-007:
      // "父亲不吃这顿，改成管理员和母亲") while the UI chips still show three.
      const result = await agent.handleUserMessage(userText);
      this.save(agent);
      return result;
    });
  }

  confirm(
    sessionId: string,
    input: {
      pendingActionId: string;
      confirmationToken: string;
      idempotencyKey: string;
      payloadHash: string;
    }
  ) {
    return this.enqueue(sessionId, async (agent) => {
      const result = agent.confirmPending(input);
      if (result.ok) this.save(agent);
      return result;
    });
  }

  cancel(sessionId: string, pendingActionId: string) {
    return this.enqueue(sessionId, async (agent) => {
      const result = agent.cancelPending(pendingActionId);
      if (result.ok) this.save(agent);
      return result;
    });
  }

  clear(sessionId: string): Promise<void> {
    const existingClear = this.clears.get(sessionId);
    if (existingClear) return existingClear;

    const record = this.getOrCreate(sessionId);
    record.accepting = false;
    const operation = record.tail.then(() => {
      if (record.agent.state.pendingActionId) {
        record.agent.cancelPending(record.agent.state.pendingActionId);
      }
      this.domain.deleteAgentCheckpoint(sessionId);
      if (this.sessions.get(sessionId) === record) {
        this.sessions.delete(sessionId);
      }
    });
    const tracked = operation.then(
      () => {
        this.clears.delete(sessionId);
      },
      (error: unknown) => {
        this.clears.delete(sessionId);
        throw error;
      }
    );
    this.clears.set(sessionId, tracked);
    return tracked;
  }

  getState(sessionId: string): AgentState {
    return { ...this.getOrCreate(sessionId).agent.state };
  }

  getAgent(sessionId: string): PrivatePlateAgentCore {
    return this.getOrCreate(sessionId).agent;
  }

  clearMemory(): void {
    this.sessions.clear();
  }

  private getOrCreate(sessionId: string): SessionRecord {
    const existing = this.sessions.get(sessionId);
    if (existing) return existing;

    const agent = new PrivatePlateAgent(
      this.domain,
      sessionId,
      this.provider
    );
    const checkpoint = this.domain.loadAgentCheckpoint(sessionId);
    if (checkpoint) {
      // V2 envelope or legacy bare AgentState — restoreState accepts both.
      agent.restoreState(checkpoint.state as never);
    }
    const record = { agent, tail: Promise.resolve(), accepting: true };
    this.sessions.set(sessionId, record);
    return record;
  }

  private enqueue<T>(
    sessionId: string,
    operation: (agent: PrivatePlateAgentCore) => Promise<T>
  ): Promise<T> {
    const record = this.getOrCreate(sessionId);
    if (!record.accepting) {
      return Promise.reject(
        new SessionInputError("该会话正在清理，请稍后重试。")
      );
    }
    const result = record.tail.then(() => operation(record.agent));
    record.tail = result.then(
      () => undefined,
      () => undefined
    );
    return result;
  }

  private save(agent: PrivatePlateAgentCore): void {
    // Persist versioned AgentState + TaskState envelope (no tokens).
    this.domain.saveAgentCheckpoint(
      agent.state.sessionId,
      agent.exportCheckpoint()
    );
  }
}

export class SessionInputError extends Error {
  readonly code = "VALIDATION_ERROR";
}
