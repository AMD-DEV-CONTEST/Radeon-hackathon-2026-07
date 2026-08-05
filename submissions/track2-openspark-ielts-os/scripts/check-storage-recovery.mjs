import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);
const [app, remote] = await Promise.all([
  readFile(new URL("app.js", root), "utf8"),
  readFile(new URL("remote-update.js", root), "utf8"),
]);

const rawAppWrites = [...app.matchAll(/localStorage\.setItem\(/g)];
const rawRemoteWrites = [...remote.matchAll(/localStorage\.setItem\(/g)];
assert.equal(rawAppWrites.length, 2, "durable writes are not routed through the reliability gateway");
assert.equal(rawRemoteWrites.length, 0, "remote durable writes are not routed through the reliability gateway");
assert.match(app, /function recordClientError[\s\S]*?try \{[\s\S]*?localStorage\.setItem\(ERROR_LOG_KEY/);
assert.match(app, /recoveries\.unshift[\s\S]*?try \{[\s\S]*?localStorage\.setItem\(RECOVERY_KEY/);
assert.match(app, /无法创建导入前快照/);
assert.match(app, /数据恢复不完整/);
assert.match(app, /IELTSReliability\.applyChanges/);
assert.match(app, /captureValues\(localStorage, targetKeys\)/);
assert.match(app, /Object\.entries\(snapshot\.data\)/);
assert.doesNotMatch(app, /history\s*=\s*history\.slice|draft\.history\s*=\s*draft\.history\.slice/, "writing history must not be truncated");
assert.doesNotMatch(app, /persistenceFailureAt|persistenceFailed|consumePersistFailure|Date\.now\(\) - persistenceFailure|< 1500/, "persistence failure reporting must not depend on global or timer heuristics");
assert.match(app, /reportPersistResult\(removePersistedValue\(REMINDER_TIME_KEY\)/);
assert.match(app, /const saved = persistWritingDrafts\(\)[\s\S]*?saved \? "已自动保存到本机"/);
assert.match(app, /function addLaterItem[\s\S]*?if \(!persistValue\(LATER_ITEMS_KEY[\s\S]*?state\.laterItems = previous[\s\S]*?showToast\(existing/);
assert.match(app, /function saveNewsSentence[\s\S]*?if \(!persistValue\(SAVED_SENTENCES_KEY[\s\S]*?state\.savedSentences = previous/);
const saveSource = app.slice(app.indexOf("function saveNewsSentence()"), app.indexOf("\nconst BACKUP_KEYS"));
const saveState = { dailyNews: [{ url: "u", summary: "s", title: "t" }], activeNewsIndex: 0, savedSentences: [] };
let saveCopy = "";
Function("state", "persistValue", "setText", "SAVED_SENTENCES_KEY", `${saveSource}; saveNewsSentence();`)(saveState, () => false, (_, value) => { saveCopy = value; }, "sentences");
assert.deepEqual(saveState.savedSentences, [], "failed production save must roll back memory");
assert.match(saveCopy, /收藏失败/);

const require = createRequire(import.meta.url);
const reliability = require(fileURLToPath(new URL("../app-reliability.js", import.meta.url)));
assert.doesNotMatch(await readFile(new URL("app-reliability.js", root), "utf8"), /structuredClone/);

class FakeStorage {
  constructor(entries = {}, fail = () => false) {
    this.data = new Map(Object.entries(entries));
    this.fail = fail;
    this.calls = [];
  }
  getItem(key) { return this.data.has(key) ? this.data.get(key) : null; }
  setItem(key, value) {
    this.calls.push(["set", key, String(value)]);
    if (this.fail("set", key, String(value), this.calls.length)) throw new Error(`quota:${key}`);
    this.data.set(key, String(value));
  }
  removeItem(key) {
    this.calls.push(["remove", key]);
    if (this.fail("remove", key, null, this.calls.length)) throw new Error(`quota:${key}`);
    this.data.delete(key);
  }
}

assert.equal(reliability.writeValue(new FakeStorage(), "ok", "1"), true);
assert.equal(reliability.writeValue(new FakeStorage({}, () => true), "no", "1"), false);
const fallback = { nested: { value: 1 } };
const optional = await reliability.loadDataSources([{ key: "optional", critical: false, fallback }], async () => { throw new Error("offline"); });
optional.values.optional.nested.value = 2;
assert.equal(fallback.nested.value, 1, "optional startup fallback must be a compatible deep copy");

const partial = new FakeStorage({ a: "old-a", b: "old-b" }, (operation, key, value) => operation === "set" && key === "b" && value === "new-b");
const partialResult = reliability.applyChanges(partial, { a: "new-a", b: "new-b" });
assert.equal(partialResult.ok, false);
assert.deepEqual(Object.fromEntries(partial.data), { a: "old-a", b: "old-b" }, "partial import must compensate changed keys");
assert.deepEqual(partialResult.compensationFailedKeys, []);

let failRestore = true;
const incomplete = new FakeStorage({ a: "old-a", b: "old-b" }, (operation, key, value) => operation === "set" && ((key === "b" && value === "new-b") || (failRestore && key === "a" && value === "old-a")));
const incompleteResult = reliability.applyChanges(incomplete, { a: "new-a", b: "new-b" });
assert.equal(incompleteResult.ok, false);
assert.deepEqual(incompleteResult.compensationFailedKeys, ["a"]);
assert.equal(incomplete.getItem("a"), "new-a");
failRestore = false;
assert.equal(reliability.applyChanges(incomplete, incompleteResult.before).ok, true, "retained snapshot must restore after storage is freed");

let failUndo = true;
const undo = new FakeStorage({ a: "imported-a", b: "imported-b" }, (operation, key, value) => operation === "set" && ((failUndo && key === "b" && value === "original-b") || (failUndo && key === "a" && value === "imported-a")));
const undoResult = reliability.applyChanges(undo, { a: "original-a", b: "original-b" });
assert.equal(undoResult.ok, false);
assert.deepEqual(undoResult.before, { a: "imported-a", b: "imported-b" }, "undo must capture immediate pre-undo values");
assert.deepEqual(undoResult.compensationFailedKeys, ["a"]);
failUndo = false;
assert.equal(reliability.applyChanges(undo, { a: "original-a", b: "original-b" }).ok, true);

const scheduled = [];
const revoked = [];
const bodyChildren = [];
let clicked = 0;
const anchor = { click: () => { clicked += 1; }, remove: () => { bodyChildren.splice(bodyChildren.indexOf(anchor), 1); } };
const documentFake = { body: { append: (node) => bodyChildren.push(node) }, createElement: () => anchor };
const urlApi = { createObjectURL: (blob) => { assert.ok(blob.size > 0); return "blob:test"; }, revokeObjectURL: (url) => revoked.push(url) };
const exported = reliability.createBrowserBackup({ payload: { version: 1, data: { a: "x" } }, filename: "backup.json", document: documentFake, urlApi, BlobCtor: Blob, setTimeoutFn: (callback, delay) => scheduled.push({ callback, delay }) });
assert.equal(exported, true);
assert.equal(clicked, 1);
assert.equal(bodyChildren.length, 0);
assert.deepEqual(scheduled.map((item) => item.delay), [1000]);
assert.equal(revoked.length, 0, "URL must not revoke at 999ms");
scheduled[0].callback();
assert.deepEqual(revoked, ["blob:test"]);

console.log("Durable storage, compensation and browser backup checks passed.");
