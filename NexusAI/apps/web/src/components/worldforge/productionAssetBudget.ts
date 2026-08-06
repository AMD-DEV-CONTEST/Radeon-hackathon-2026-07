import type { ProductionEnvironmentAsset } from "./environmentAssetManifest";

export type ProductionAssetBudget = {
  requested: number;
  allowed: number;
  suppressed: number;
};

const MAX_PRODUCTION_INSTANCES_PER_ASSET = 3;
const MAX_PRODUCTION_INSTANCES_PER_BIOME = 6;

export function budgetForAsset(
  asset: ProductionEnvironmentAsset,
): ProductionAssetBudget {
  const requested = Math.max(0, Math.floor(asset.density));

  const allowed = Math.min(
    requested,
    MAX_PRODUCTION_INSTANCES_PER_ASSET,
  );

  return {
    requested,
    allowed,
    suppressed: requested - allowed,
  };
}

export function enforceBiomeBudget(
  assets: ProductionEnvironmentAsset[],
): Array<{
  asset: ProductionEnvironmentAsset;
  count: number;
}> {
  let remaining = MAX_PRODUCTION_INSTANCES_PER_BIOME;

  return assets.map((asset) => {
    const budget = budgetForAsset(asset);
    const count = Math.min(budget.allowed, remaining);

    remaining = Math.max(0, remaining - count);

    return {
      asset,
      count,
    };
  });
}