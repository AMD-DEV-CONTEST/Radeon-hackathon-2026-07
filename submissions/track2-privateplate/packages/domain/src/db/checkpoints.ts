import type { Db } from "./open-db.js";

export type JsonPrimitive = null | boolean | number | string;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export type JsonObject = { [key: string]: JsonValue };

export type AgentCheckpoint<TState = JsonObject> = {
  sessionId: string;
  householdId: string;
  state: TState;
  updatedAt: string;
};

export function saveAgentCheckpoint<TState extends object>(
  db: Db,
  input: {
    sessionId: string;
    householdId: string;
    state: TState;
    updatedAt: string;
  }
): AgentCheckpoint<TState> {
  assertSerializableCheckpoint(input.state);
  const stateJson = JSON.stringify(input.state);

  db.prepare(
    `INSERT INTO agent_checkpoints (session_id, household_id, state_json, updated_at)
     VALUES (?, ?, ?, ?)
     ON CONFLICT(household_id, session_id) DO UPDATE SET
       state_json = excluded.state_json,
       updated_at = excluded.updated_at`
  ).run(input.sessionId, input.householdId, stateJson, input.updatedAt);

  return {
    sessionId: input.sessionId,
    householdId: input.householdId,
    state: input.state,
    updatedAt: input.updatedAt
  };
}

export function loadAgentCheckpoint<TState = JsonObject>(
  db: Db,
  householdId: string,
  sessionId: string
): AgentCheckpoint<TState> | null {
  const checkpoint = db
    .prepare(
      `SELECT session_id, household_id, state_json, updated_at
       FROM agent_checkpoints
       WHERE session_id = ? AND household_id = ?`
    )
    .get(sessionId, householdId) as
    | {
        session_id: string;
        household_id: string;
        state_json: string;
        updated_at: string;
      }
    | undefined;

  if (!checkpoint) return null;
  return {
    sessionId: checkpoint.session_id,
    householdId: checkpoint.household_id,
    state: JSON.parse(checkpoint.state_json) as TState,
    updatedAt: checkpoint.updated_at
  };
}

export function deleteAgentCheckpoint(
  db: Db,
  householdId: string,
  sessionId: string
): boolean {
  const result = db
    .prepare(
      `DELETE FROM agent_checkpoints
       WHERE session_id = ? AND household_id = ?`
    )
    .run(sessionId, householdId);
  return Number(result.changes) === 1;
}

function assertSerializableCheckpoint(
  value: unknown,
  seen = new WeakSet<object>()
): void {
  if (Array.isArray(value)) {
    if (seen.has(value)) {
      throw new Error("Agent checkpoints must not contain circular values");
    }
    seen.add(value);
    value.forEach((item) => assertSerializableCheckpoint(item, seen));
    return;
  }
  if (value === null || ["string", "number", "boolean"].includes(typeof value)) {
    return;
  }
  if (typeof value !== "object") {
    throw new Error("Agent checkpoints must contain JSON-serializable values");
  }
  if (seen.has(value)) {
    throw new Error("Agent checkpoints must not contain circular values");
  }
  seen.add(value);

  for (const [key, child] of Object.entries(value)) {
    const normalizedKey = key.replaceAll("_", "").replaceAll("-", "").toLowerCase();
    if (normalizedKey === "confirmationtoken") {
      throw new Error("Agent checkpoints must not contain a plaintext confirmation token");
    }
    assertSerializableCheckpoint(child, seen);
  }
}
