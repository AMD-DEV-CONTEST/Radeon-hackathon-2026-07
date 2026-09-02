import {
  useActivationContext,
  useOptionalActivationContext,
} from "./ActivationProvider";

export function useActivation() {
  return useActivationContext();
}

export function useOptionalActivation() {
  return useOptionalActivationContext();
}
