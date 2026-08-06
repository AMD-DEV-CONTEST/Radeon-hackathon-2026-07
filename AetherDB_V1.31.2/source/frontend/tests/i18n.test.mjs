import test from "node:test";
import assert from "node:assert/strict";

import {
  LOCALE_STORAGE_KEY,
  normalizeLocale,
  resolvePersistedLocale,
} from "../src/i18n/index.js";


test("locale normalization accepts only the frozen zh-CN and en-US set", () => {
  assert.equal(normalizeLocale("zh_CN"), "zh-CN");
  assert.equal(normalizeLocale("zh-Hans"), "zh-CN");
  assert.equal(normalizeLocale("en"), "en-US");
  assert.equal(normalizeLocale("fr-FR"), null);
  assert.equal(normalizeLocale(null), null);
});

test("persisted locale survives restart without trusting invalid storage", () => {
  const values = new Map([[LOCALE_STORAGE_KEY, "en-US"]]);
  const storage = { getItem: (key) => values.get(key) || null };
  assert.equal(resolvePersistedLocale(storage), "en-US");

  values.set(LOCALE_STORAGE_KEY, "unsupported");
  assert.equal(resolvePersistedLocale(storage), null);
  assert.equal(resolvePersistedLocale({ getItem: () => { throw new Error("blocked"); } }), null);
});
