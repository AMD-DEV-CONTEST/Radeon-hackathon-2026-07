import { randomBytes } from "node:crypto";
import type { Actor, Event, EventKind } from "../types.js";

/** Stable-ish short id for ingested events. */
export function newEventId(prefix = "ing"): string {
  const t = Date.now().toString(36);
  const r = randomBytes(3).toString("hex");
  return `${prefix}_${t}_${r}`;
}

export function nowIso(d = new Date()): string {
  return d.toISOString();
}

export function makeEvent<K extends EventKind>(
  partial: Omit<Extract<Event, { kind: K }>, "id" | "ts" | "signal" | "refs"> &
    Partial<Pick<Event, "id" | "ts" | "signal" | "refs" | "actor">>,
): Extract<Event, { kind: K }> {
  const {
    id,
    ts,
    signal,
    refs,
    actor,
    ...rest
  } = partial as typeof partial & {
    id?: string;
    ts?: string;
    signal?: Event["signal"];
    refs?: Event["refs"];
    actor?: Actor;
  };
  return {
    ...rest,
    id: id ?? newEventId(),
    ts: ts ?? nowIso(),
    signal: signal ?? "high",
    refs: refs ?? [],
    actor: (actor ?? "tool") as Actor,
  } as Extract<Event, { kind: K }>;
}
