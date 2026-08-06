// Unit tests for the E02 project-actions deep module.
//
// These tests inject fake `rpc`/`dialogs` objects and never touch Electron,
// the DOM, `window`, or the real Python backend. That is the point of the
// module: it must be fully testable under plain `node --test`.

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  deriveSafeId,
  createProject,
  importAsset,
} from '../renderer/js/project-actions.js';

const ID_PATTERN = /^[a-z0-9_]+$/;

function makeRpc(handler) {
  const calls = [];
  return {
    calls,
    async call(method, params) {
      calls.push({ method, params });
      return handler(method, params, calls.length);
    },
  };
}

// Deliberately has no methods: any accidental use of rpc/dialogs in a code
// path that should not need it blows up loudly instead of silently passing.
const UNUSED = undefined;

// ---------------------------------------------------------------------------
// deriveSafeId
// ---------------------------------------------------------------------------

test('deriveSafeId: Chinese name becomes a stable ascii id', () => {
  const id = deriveSafeId('英雄行走动画');
  assert.match(id, ID_PATTERN, `id "${id}" must match ${ID_PATTERN}`);
  assert.equal(id, deriveSafeId('英雄行走动画'), 'must be deterministic across calls');
});

test('deriveSafeId: different Chinese names get different stable ids', () => {
  const a = deriveSafeId('英雄行走动画');
  const b = deriveSafeId('道具图标');
  assert.notEqual(a, b);
  assert.match(a, ID_PATTERN);
  assert.match(b, ID_PATTERN);
});

test('deriveSafeId: mixed ascii/unicode/punctuation name is sanitized, not hashed away', () => {
  const id = deriveSafeId('Hero Walk-01 (英雄)');
  assert.match(id, ID_PATTERN);
  // The ascii content should survive recognizably instead of being thrown
  // away in favor of the hash fallback.
  assert.ok(id.startsWith('hero_walk_01'), `expected ascii content to survive, got "${id}"`);
});

test('deriveSafeId: already-safe ascii id is stable and effectively unchanged', () => {
  assert.equal(deriveSafeId('hero_walk_01'), 'hero_walk_01');
});

test('deriveSafeId: empty/whitespace-only input still produces a valid safe id', () => {
  const id = deriveSafeId('   ');
  assert.match(id, ID_PATTERN);
  assert.equal(id, deriveSafeId('   '));
});

// ---------------------------------------------------------------------------
// createProject
// ---------------------------------------------------------------------------

test('createProject: rejects an empty name without touching rpc or dialogs', async () => {
  const res = await createProject({ name: '   ' }, { rpc: UNUSED, dialogs: UNUSED });
  assert.equal(res.ok, false);
  assert.equal(res.cancelled, undefined);
  assert.equal(res.error.code, 2);
});

test('createProject: cancelling the parent-directory picker returns cancelled, not an error', async () => {
  const dialogs = { chooseProjectParent: async () => null };
  const res = await createProject({ name: '英雄' }, { rpc: UNUSED, dialogs });
  assert.deepEqual(res, { ok: false, cancelled: true });
});

test('createProject: surfaces an RPC failure unchanged', async () => {
  const rpcError = { code: 7, message: 'target directory is not empty' };
  const rpc = makeRpc(async () => ({ ok: false, error: rpcError }));
  const dialogs = { chooseProjectParent: async () => '/tmp/projects' };

  const res = await createProject({ name: 'Hero' }, { rpc, dialogs });
  assert.equal(res.ok, false);
  assert.equal(res.cancelled, undefined);
  assert.deepEqual(res.error, rpcError);
  assert.equal(rpc.calls.length, 1);
  assert.equal(rpc.calls[0].method, 'project.create');
});

test('createProject: success with a Chinese name derives a safe id and builds the path', async () => {
  const rpc = makeRpc(async (method, params) => {
    assert.equal(method, 'project.create');
    return {
      ok: true,
      result: {
        project_id: params.id,
        name: params.name,
        path: params.path,
        schema_version: 1,
        head_revision: 0,
        defaults: {},
      },
    };
  });
  const dialogs = { chooseProjectParent: async () => '/tmp/projects' };

  const res = await createProject({ name: '英雄工程' }, { rpc, dialogs });
  assert.equal(res.ok, true);
  assert.match(res.id, ID_PATTERN);
  assert.equal(res.path, `/tmp/projects/${res.id}`);
  assert.equal(res.project.project_id, res.id);
  assert.equal(res.project.name, '英雄工程');

  const call = rpc.calls[0];
  assert.equal(call.params.name, '英雄工程');
  assert.equal(call.params.id, res.id);
  assert.equal(call.params.path, res.path);
});

test('createProject: explicit parentDir skips the dialog entirely', async () => {
  const rpc = makeRpc(async (_method, params) => ({
    ok: true,
    result: { project_id: params.id, name: params.name, path: params.path },
  }));
  const res = await createProject(
    { name: 'Hero', parentDir: '/tmp/projects' },
    { rpc, dialogs: UNUSED },
  );
  assert.equal(res.ok, true);
  assert.equal(res.path, '/tmp/projects/hero');
});

test('createProject: an invalid explicit id is rejected locally', async () => {
  const res = await createProject(
    { name: 'Hero', id: 'Not Valid!' },
    { rpc: UNUSED, dialogs: { chooseProjectParent: async () => '/tmp/projects' } },
  );
  assert.equal(res.ok, false);
  assert.equal(res.error.code, 2);
});

// ---------------------------------------------------------------------------
// importAsset
// ---------------------------------------------------------------------------

test('importAsset: cancelling the file picker returns cancelled, not an error', async () => {
  const dialogs = { chooseImportImage: async () => null };
  const res = await importAsset({}, { rpc: UNUSED, dialogs });
  assert.deepEqual(res, { ok: false, cancelled: true });
});

test('importAsset: surfaces an RPC failure unchanged', async () => {
  const rpcError = { code: 3, message: 'no project open' };
  const rpc = makeRpc(async () => ({ ok: false, error: rpcError }));
  const dialogs = { chooseImportImage: async () => '/tmp/hero.png' };

  const res = await importAsset({}, { rpc, dialogs });
  assert.equal(res.ok, false);
  assert.deepEqual(res.error, rpcError);
});

test('importAsset: success derives a safe asset name from a Chinese filename', async () => {
  const rpc = makeRpc(async (method, params) => {
    assert.equal(method, 'asset.import');
    assert.match(params.as, ID_PATTERN);
    return { ok: true, result: { asset: params.as, kind: 'source', revision: 1 } };
  });
  const dialogs = { chooseImportImage: async () => 'C:\\imports\\英雄.png' };

  const res = await importAsset({}, { rpc, dialogs });
  assert.equal(res.ok, true);
  assert.equal(res.asset, rpc.calls[0].params.as);
  assert.equal(res.revision, 1);
  assert.equal(res.path, 'C:\\imports\\英雄.png');
});

test('importAsset: explicit path skips the dialog', async () => {
  const rpc = makeRpc(async (_method, params) => ({
    ok: true,
    result: { asset: params.as, kind: 'source', revision: 1 },
  }));
  const res = await importAsset({ path: '/tmp/hero.png' }, { rpc, dialogs: UNUSED });
  assert.equal(res.ok, true);
  assert.equal(res.asset, 'hero');
});

test('importAsset: duplicate import surfaces the backend rejection on the second call', async () => {
  let calls = 0;
  const rpc = makeRpc(async (_method, params) => {
    calls += 1;
    if (calls === 1) {
      return { ok: true, result: { asset: params.as, kind: 'source', revision: 1 } };
    }
    return {
      ok: false,
      error: { code: 7, message: 'source already exists', name: params.as },
    };
  });
  const dialogs = { chooseImportImage: async () => '/tmp/hero.png' };

  const first = await importAsset({}, { rpc, dialogs });
  assert.equal(first.ok, true);
  assert.equal(first.asset, 'hero');

  const second = await importAsset({}, { rpc, dialogs });
  assert.equal(second.ok, false);
  assert.equal(second.cancelled, undefined);
  assert.equal(second.error.code, 7);

  assert.equal(rpc.calls.length, 2, 'module must not cache or dedupe across calls');
});

test('importAsset: an invalid explicit "as" is rejected locally', async () => {
  const res = await importAsset(
    { path: '/tmp/hero.png', as: 'Not Valid!' },
    { rpc: UNUSED, dialogs: UNUSED },
  );
  assert.equal(res.ok, false);
  assert.equal(res.error.code, 2);
});
