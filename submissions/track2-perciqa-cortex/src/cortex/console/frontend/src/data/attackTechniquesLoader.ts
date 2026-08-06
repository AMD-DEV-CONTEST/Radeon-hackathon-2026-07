import tsv from "./attack-techniques.tsv?raw";
import type { TechniqueEntry } from "./attackTechniques";

export function loadAttackTechniques(): Record<string, TechniqueEntry> {
  const map: Record<string, TechniqueEntry> = {};
  for (const line of tsv.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const [id, ...rest] = trimmed.split("\t");
    const name = rest.join(" ").trim() || id;
    if (id) map[id] = { name, severity: "medium" };
  }
  return map;
}
