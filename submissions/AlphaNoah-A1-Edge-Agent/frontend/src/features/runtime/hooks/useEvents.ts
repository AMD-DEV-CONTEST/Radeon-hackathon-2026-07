import { useMemo } from "react";

import type { EventView } from "../models";
import { useWorkspace } from "./useWorkspace";

export interface EventsSelection {
  readonly events: readonly EventView[];
  readonly selectedEvent: EventView | null;
}

export function useEvents(
  selectedEventId: string | null = null,
): EventsSelection {
  const { data } = useWorkspace();

  return useMemo(() => {
    const events = data?.events ?? [];
    return {
      events,
      selectedEvent:
        events.find((event) => event.id === selectedEventId) ??
        null,
    };
  }, [data, selectedEventId]);
}
