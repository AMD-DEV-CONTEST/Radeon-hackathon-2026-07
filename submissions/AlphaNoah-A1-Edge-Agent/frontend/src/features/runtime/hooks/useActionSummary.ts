import type { ActionSummary } from "../models";
import { useWorkspace } from "./useWorkspace";

export function useActionSummary(
  eventId: string | null,
  actionSummaryId?: string | null,
): ActionSummary | null {
  const { data } = useWorkspace();
  if (!data || eventId === null) {
    return null;
  }

  const expectedActionSummaryId =
    actionSummaryId === undefined
      ? (data.events.find((event) => event.id === eventId)
          ?.actionSummaryId ?? null)
      : actionSummaryId;

  if (expectedActionSummaryId === null) {
    return null;
  }

  return data.actionSummaries.find(
    (summary) =>
      summary.id === expectedActionSummaryId &&
      summary.eventId === eventId,
  ) ?? null;
}
