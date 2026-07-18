import tsv from "./attack-techniques.tsv?raw";

export function loadAttackTechniques(): string[] {
  return tsv.split("\n").map(r => r.trim()).filter(Boolean).map(r => r.split("\t")[0]);
}
