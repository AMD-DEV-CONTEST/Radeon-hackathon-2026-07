import type { HealthView } from "../models";
import { useWorkspace } from "./useWorkspace";

export function useHealth(): HealthView | null {
  return useWorkspace().data?.health ?? null;
}
