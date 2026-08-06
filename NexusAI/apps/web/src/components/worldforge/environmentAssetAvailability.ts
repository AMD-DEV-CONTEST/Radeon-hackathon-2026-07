import type { EnvironmentRenderSpec } from "./environmentTypes";

/**
 * Production assets are opt-in because React/Three loaders cannot reliably
 * distinguish a deliberately absent local GLB before requesting it.
 * Set NEXT_PUBLIC_WORLDFORGE_PRODUCTION_ASSETS=true after populating the
 * public asset manifest paths.
 */
export function productionEnvironmentAssetsEnabled(
  spec: EnvironmentRenderSpec | null,
): boolean {
  return Boolean(spec) &&
    process.env.NEXT_PUBLIC_WORLDFORGE_PRODUCTION_ASSETS === "true";
}
