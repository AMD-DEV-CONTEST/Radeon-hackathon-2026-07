import { EntityKind } from "./types";

export function normalizeEntityType(type: string): string {
  return type.trim().toLowerCase();
}

export function entityKind(type: string): EntityKind {
  const t = normalizeEntityType(type);

  if (["person", "character"].includes(t))
    return "PERSON";

  if (
    ["place", "location", "city", "country"].includes(t)
  )
    return "PLACE";

  if (
    ["organization", "organisation", "company", "lab"].includes(t)
  )
    return "ORGANIZATION";

  if (
    ["project", "product"].includes(t)
  )
    return "PROJECT";

  if (
    ["system", "ai", "agent"].includes(t)
  )
    return "SYSTEM";

  return "UNKNOWN";
}