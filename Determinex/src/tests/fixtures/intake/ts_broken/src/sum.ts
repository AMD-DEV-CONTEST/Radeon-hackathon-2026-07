// Intentionally broken: returns a string but signature says number.
// LLM_MOCKED_INTAKE_REPAIR_LOCK_001 — mocked diagnostic targets this file.
export function sum(a: number, b: number): number {
  return `${a + b}`;
}
