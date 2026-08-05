(function attachReliability(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.IELTSReliability = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createReliability() {
  const APP_DATA_SOURCES = [
    { key: "wordbook", path: "./data/wordbook.json", critical: true },
    { key: "practice", path: "./data/practice.json", critical: true },
    { key: "wrongQuestions", path: "./data/wrong-questions.json", critical: false, fallback: { items: [], notes: [] } },
    { key: "reading", path: "./data/reading.json", critical: true },
    { key: "tests", path: "./data/tests.json", critical: true },
    { key: "listening", path: "./data/listening.json", critical: true },
    { key: "writing", path: "./data/writing.json", critical: true },
    { key: "synonyms", path: "./data/synonyms.json", critical: false, fallback: { groups: [], source: "", title: "" } },
    { key: "contentManifest", path: "./data/content-manifest.json", critical: false, fallback: { version: 0, records: [], description: "" } },
    { key: "contentRoadmap", path: "./data/content-roadmap.json", critical: false, fallback: { schemaVersion: 0, books: [], stages: [], gaps: [], reservations: [] } },
    { key: "audioMap", path: "./data/audio-map.json", critical: false, fallback: { version: 0, items: [], policy: "" } },
    { key: "libraryCatalog", path: "./content-packs/library-catalog.json", critical: false, fallback: { schemaVersion: 0, modules: [], personalCollections: [], totalResources: 0, status: "partial" } },
    { key: "studyPaths", path: "./data/study-paths.json", critical: false, fallback: { version: 0, paths: [] } },
  ];

  function writeValue(storage, key, value) {
    try {
      storage.setItem(key, String(value));
      return true;
    } catch (_) {
      return false;
    }
  }

  function removeValue(storage, key) {
    try {
      storage.removeItem(key);
      return true;
    } catch (_) {
      return false;
    }
  }

  function captureValues(storage, keys) {
    try { return Object.fromEntries(keys.map((key) => [key, storage.getItem(key)])); }
    catch (_) { throw new Error("storage read failed"); }
  }

  function applyChanges(storage, changes) {
    const entries = Object.entries(changes);
    const before = captureValues(storage, entries.map(([key]) => key));
    const changedKeys = [];
    let failedKey = null;
    for (const [key, value] of entries) {
      const ok = value === null ? removeValue(storage, key) : writeValue(storage, key, value);
      if (!ok) {
        failedKey = key;
        break;
      }
      changedKeys.push(key);
    }
    if (!failedKey) return { ok: true, before, changedKeys, failedKey: null, compensationFailedKeys: [] };
    const compensationFailedKeys = [];
    for (const key of [...changedKeys].reverse()) {
      const value = before[key];
      const ok = value === null ? removeValue(storage, key) : writeValue(storage, key, value);
      if (!ok) compensationFailedKeys.push(key);
    }
    return { ok: false, before, changedKeys, failedKey, compensationFailedKeys };
  }

  function createBrowserBackup({ payload, filename, document, urlApi, BlobCtor, setTimeoutFn }) {
    try {
      const blob = new BlobCtor([JSON.stringify(payload, null, 2)], { type: "application/json" });
      if (!blob.size) return false;
      const url = urlApi.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeoutFn(() => urlApi.revokeObjectURL(url), 1000);
      return true;
    } catch (_) {
      return false;
    }
  }

  async function loadDataSources(sources, load) {
    const settled = await Promise.allSettled(sources.map((source) => load(source)));
    const missing = sources.filter((_, index) => settled[index].status === "rejected").map((source) => source.key);
    const criticalMissing = sources.some((source, index) => source.critical && settled[index].status === "rejected");
    if (criticalMissing) return { ok: false, missing, values: null };
    const values = {};
    sources.forEach((source, index) => {
      values[source.key] = settled[index].status === "fulfilled" ? settled[index].value : JSON.parse(JSON.stringify(source.fallback));
    });
    return { ok: true, missing, values };
  }

  function applyStartupDomState({ status, phone, overlay, nav, screens }) {
    const blocked = status !== "ready";
    phone?.classList?.toggle("startup-blocked", blocked);
    if (overlay) {
      overlay.hidden = !blocked;
      overlay.setAttribute("aria-busy", String(status === "loading"));
    }
    for (const screen of screens || []) screen.toggleAttribute("inert", blocked);
    nav?.toggleAttribute("inert", blocked);
    if (blocked) nav?.setAttribute("aria-hidden", "true");
    else nav?.removeAttribute("aria-hidden");
  }

  function mergeBackupValue(current, incoming) {
    if (!current) return incoming;
    try {
      const existingData = JSON.parse(current);
      const incomingData = JSON.parse(incoming);
      if (Array.isArray(existingData) && Array.isArray(incomingData)) {
        const identity = (item) => item?.id || item?.word || item?.sourceId || JSON.stringify(item);
        const merged = new Map(existingData.map((item) => [identity(item), item]));
        incomingData.forEach((item) => merged.set(identity(item), item));
        return JSON.stringify([...merged.values()]);
      }
      if (existingData && incomingData && typeof existingData === "object" && typeof incomingData === "object") {
        return JSON.stringify({ ...existingData, ...incomingData });
      }
    } catch (_) {}
    return incoming;
  }

  return { APP_DATA_SOURCES, writeValue, removeValue, captureValues, applyChanges, createBrowserBackup, loadDataSources, applyStartupDomState, mergeBackupValue };
});
