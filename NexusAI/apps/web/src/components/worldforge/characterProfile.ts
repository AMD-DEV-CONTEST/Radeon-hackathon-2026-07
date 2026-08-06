import type { WorldForgeEntity } from "@/lib/api";
import type { EnvironmentRenderSpec } from "./environmentTypes";
import type { CharacterClothing, CharacterProfile } from "./characterTypes";

const SKIN = ["#f2d0b1", "#ddb08a", "#bd8967", "#8d5e43", "#654331"];
const HAIR = ["#17120f", "#2d211b", "#4b3428", "#6a4a32", "#242424"];

const PALETTES: Record<CharacterClothing, [string, string, string][]> = {
  desert: [["#b89b72", "#594b3a", "#d0b487"], ["#967657", "#44392f", "#c6a36d"]],
  arctic: [["#d6e0e5", "#52616b", "#a9c4d2"], ["#b9c9d2", "#35434d", "#e2edf2"]],
  forest: [["#536348", "#313b2d", "#7a6c4d"], ["#40513d", "#292f29", "#6d7c56"]],
  urban: [["#344155", "#1d2530", "#78879a"], ["#493f4b", "#252229", "#9a8796"]],
  coastal: [["#688b91", "#394d52", "#c0aa7b"], ["#47747b", "#2f4145", "#b99265"]],
  traveler: [["#715f4e", "#34302c", "#9a7d5d"]],
  neutral: [["#4b5563", "#252a31", "#8b96a6"]],
};

function hash(value: string): number {
  let h = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function unit(seed: number, salt: number): number {
  const x = Math.sin((seed + salt * 101) * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}

export function resolveCharacterClothing(
  spec: EnvironmentRenderSpec | null,
): CharacterClothing {
  const biome = spec?.biome?.toLowerCase() ?? "";
  if (biome.includes("desert")) return "desert";
  if (biome.includes("arctic") || biome.includes("snow")) return "arctic";
  if (biome.includes("forest") || biome.includes("grass")) return "forest";
  if (biome.includes("coastal")) return "coastal";
  if (biome.includes("urban")) return "urban";

  const context = spec?.character_context?.toLowerCase() ?? "";
  if (context.includes("traveler") || context.includes("nomad")) return "traveler";
  return "neutral";
}

export function buildCharacterProfile(
  entity: WorldForgeEntity,
  spec: EnvironmentRenderSpec | null,
): CharacterProfile {
  const seed = hash(`${entity.id}:${entity.name}`);
  const clothing = resolveCharacterClothing(spec);
  const palette = PALETTES[clothing][seed % PALETTES[clothing].length];
  const properties = entity.properties ?? {};
  const explicitModel =
    typeof properties.model_url === "string" ? properties.model_url : undefined;

  return {
    seed,
    height: 0.92 + unit(seed, 1) * 0.14,
    build: 0.9 + unit(seed, 2) * 0.18,
    skinTone: SKIN[Math.floor(unit(seed, 3) * SKIN.length) % SKIN.length],
    hairColor: HAIR[Math.floor(unit(seed, 4) * HAIR.length) % HAIR.length],
    clothing,
    upperColor: palette[0],
    lowerColor: palette[1],
    accentColor: palette[2],
    modelUrl: explicitModel,
  };
}
