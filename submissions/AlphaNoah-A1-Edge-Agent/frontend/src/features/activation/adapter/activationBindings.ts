const demoOwnerEmployeeBinding: Readonly<Record<string, string>> = {
  maintenance_001: "equipment-maintenance",
};

export function bindDemoOwnerToEmployee(
  ownerId: string,
  matchType: string,
): string | null {
  if (matchType === "unassigned" || ownerId === "UNASSIGNED") {
    return null;
  }
  return demoOwnerEmployeeBinding[ownerId] ?? null;
}
