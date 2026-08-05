import { ADDONS } from "@/lib/addons";

export const ADDON_STORAGE_KEY = "determinex.addons.installed";
export const LEGACY_ADDON_STORAGE_KEY = "determinex-ext-installed";
export const ADDONS_UPDATED_EVENT = "addons-updated";

export function defaultInstalledAddonIds(): Set<string> {
  return new Set(
    ADDONS.filter((a) => a.status === "installed" || a.status === "builtin").map((a) => a.id)
  );
}

function parseAddonIds(raw: string | null): string[] {
  if (!raw) return [];
  const parsed = JSON.parse(raw);
  return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === "string") : [];
}

/** Addons that genuinely cannot be uninstalled, as opposed to merely seeded as present. */
function builtinAddonIds(): Set<string> {
  return new Set(ADDONS.filter((a) => a.status === "builtin").map((a) => a.id));
}

export function readInstalledAddonIds(storage: Storage): Set<string> {
  const builtins = builtinAddonIds();
  const stored = storage.getItem(ADDON_STORAGE_KEY);
  const current = parseAddonIds(stored);
  const legacy = parseAddonIds(storage.getItem(LEGACY_ADDON_STORAGE_KEY));

  // UNINSTALL USED TO NEVER PERSIST (fixed 2026-07-30). This merged defaultInstalledAddonIds()
  // -- which includes every addon whose STATIC status is "installed" -- back in on every read,
  // while writeInstalledAddonIds only excluded "builtin". So clicking Uninstall on a seeded addon
  // wrote a list without it and the very next read put it straight back; reload and it was
  // "Installed" again.
  //
  // The distinction that was missing: "builtin" means genuinely not removable, whereas
  // "installed" in the static list is only a FIRST-RUN SEED. Once the user has an explicit stored
  // list, that list is authoritative and only builtins are forced back in.
  if (stored !== null) {
    return new Set([...builtins, ...current]);
  }

  // First run (or legacy migration): seed from the static list.
  const seeded = new Set([...defaultInstalledAddonIds(), ...legacy]);
  if (legacy.length > 0) {
    writeInstalledAddonIds(storage, seeded);
  }
  return seeded;
}

export function writeInstalledAddonIds(storage: Storage, installed: Set<string>): string[] {
  const userInstalled = [...installed].filter((id) => {
    const addon = ADDONS.find((a) => a.id === id);
    return addon && addon.status !== "builtin";
  });
  storage.setItem(ADDON_STORAGE_KEY, JSON.stringify(userInstalled));
  return userInstalled;
}
