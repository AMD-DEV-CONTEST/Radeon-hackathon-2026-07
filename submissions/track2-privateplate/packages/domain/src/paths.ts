import { fileURLToPath } from "node:url";
import path from "node:path";

export function projectRootFromDomainPackage(): string {
  // packages/domain/src -> repo root
  return fileURLToPath(new URL("../../..", import.meta.url));
}

export function fixturePath(...parts: string[]): string {
  return path.join(projectRootFromDomainPackage(), "fixtures", ...parts);
}
