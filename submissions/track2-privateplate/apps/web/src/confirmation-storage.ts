import type { UiOnly } from "./api";

const SESSION_ID_KEY = "privateplate:session-id";

export function loadSessionId(): string {
  const existing = window.localStorage.getItem(SESSION_ID_KEY);
  if (existing) return existing;
  const created = `web-${window.crypto.randomUUID()}`;
  window.localStorage.setItem(SESSION_ID_KEY, created);
  return created;
}

function confirmationKey(sessionId: string): string {
  return `privateplate:confirmation:${sessionId}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

function isGramRange(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    (value.estimateG === null || typeof value.estimateG === "number") &&
    (value.minG === null || typeof value.minG === "number") &&
    (value.maxG === null || typeof value.maxG === "number") &&
    typeof value.confidence === "string" &&
    (value.conversionRuleId === null ||
      typeof value.conversionRuleId === "string")
  );
}

function isTaskCard(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    typeof value.planId === "string" &&
    typeof value.planVersion === "number" &&
    typeof value.recipientLabel === "string" &&
    typeof value.serveAt === "string" &&
    typeof value.disclosurePolicyVersion === "string" &&
    Array.isArray(value.menu) &&
    value.menu.every(
      (item) =>
        isRecord(item) &&
        typeof item.templateId === "string" &&
        typeof item.displayName === "string"
    ) &&
    Array.isArray(value.useFromInventory) &&
    value.useFromInventory.every(
      (item) =>
        isRecord(item) &&
        typeof item.foodId === "string" &&
        isGramRange(item.quantity)
    ) &&
    Array.isArray(value.shoppingItems) &&
    value.shoppingItems.every(
      (item) =>
        isRecord(item) &&
        typeof item.foodId === "string" &&
        typeof item.status === "string" &&
        isGramRange(item.purchase)
    ) &&
    Array.isArray(value.executionNotes) &&
    value.executionNotes.every((note) => typeof note === "string")
  );
}

function isUiOnly(value: unknown): value is UiOnly {
  if (!isRecord(value)) return false;
  return (
    typeof value.pendingActionId === "string" &&
    typeof value.confirmationToken === "string" &&
    typeof value.payloadHash === "string" &&
    typeof value.expiresAt === "string" &&
    (value.taskCard === undefined || isTaskCard(value.taskCard))
  );
}

export function loadConfirmation(sessionId: string): UiOnly | null {
  const serialized = window.sessionStorage.getItem(confirmationKey(sessionId));
  if (!serialized) return null;
  try {
    const parsed: unknown = JSON.parse(serialized);
    if (!isUiOnly(parsed)) {
      window.sessionStorage.removeItem(confirmationKey(sessionId));
      return null;
    }
    const expiresAt = Date.parse(parsed.expiresAt);
    if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
      window.sessionStorage.removeItem(confirmationKey(sessionId));
      return null;
    }
    return parsed;
  } catch {
    window.sessionStorage.removeItem(confirmationKey(sessionId));
    return null;
  }
}

export function saveConfirmation(
  sessionId: string,
  value: UiOnly | null
): void {
  const key = confirmationKey(sessionId);
  if (value) {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } else {
    window.sessionStorage.removeItem(key);
  }
}
