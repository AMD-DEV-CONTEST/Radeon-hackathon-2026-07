import { loadAttackTechniques } from "./attackTechniquesLoader";

export interface TechniqueEntry {
  name: string;
  severity: string;
}

export const ATTACK_TECHNIQUES: Record<string, TechniqueEntry> = loadAttackTechniques();
