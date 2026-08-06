export type FinalizationMode = "model" | "trusted_presenter";

export type TurnFinalizationMode =
  | FinalizationMode
  | "deterministic_fallback";

export function resolveFinalizationMode(
  value = process.env.PRIVATEPLATE_FINALIZATION_MODE
): FinalizationMode {
  const mode = value?.trim() || "model";
  if (mode === "model" || mode === "trusted_presenter") return mode;
  throw new Error(
    `Unsupported PRIVATEPLATE_FINALIZATION_MODE: ${mode}. Use model or trusted_presenter.`
  );
}
