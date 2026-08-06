export type CharacterClothing =
  | "desert"
  | "arctic"
  | "forest"
  | "urban"
  | "coastal"
  | "traveler"
  | "neutral";

export type CharacterProfile = {
  seed: number;
  height: number;
  build: number;
  skinTone: string;
  hairColor: string;
  clothing: CharacterClothing;
  upperColor: string;
  lowerColor: string;
  accentColor: string;
  modelUrl?: string;
};
