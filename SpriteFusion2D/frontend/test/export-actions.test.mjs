// Unit tests for the E04 export-actions deep module.
//
// These tests inject fake `rpc`/`dialogs` objects and never touch Electron,
// the DOM, `window`, or the real Python backend. That is the point of the
// module: it must be fully testable under plain `node --test`.

import test from 'node:test';
import assert from 'node:assert/strict';
import { exportAsset } from '../renderer/js/export-actions.js';

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

// A realistic export.apply success reply, shaped like the real backend
// (tests/test_workshop_export_rpc.py, Success.test_atlas_export_with_pack_options).
function atlasSuccessResult(overrides = {}) {
  return {
    asset: 'hero',
    format: 'generic-json',
    directory: 'C:\\out',
    files: [
      { name: 'chouko.json', bytes: 512 },
      { name: 'page_0.png', bytes: 331 },
    ],
    revision: 2,
    warnings: [],
    metrics: { pages: 1, fill_ratio: 0.42 },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// No asset
// ---------------------------------------------------------------------------

test('exportAsset: missing asset is rejected locally, without touching rpc or dialogs', async () => {
  const res = await exportAsset({}, { rpc: UNUSED, dialogs: UNUSED });
  assert.equal(res.ok, false);
  assert.equal(res.cancelled, undefined);
  assert.equal(res.error.code, 2);
});

test('exportAsset: whitespace-only asset is rejected locally', async () => {
  const res = await exportAsset({ asset: '   ' }, { rpc: UNUSED, dialogs: UNUSED });
  assert.equal(res.ok, false);
  assert.equal(res.error.code, 2);
});

// ---------------------------------------------------------------------------
// Cancel
// ---------------------------------------------------------------------------

test('exportAsset: cancelling the export-directory picker returns cancelled, not an error', async () => {
  const dialogs = { chooseExportDir: async () => null };
  const res = await exportAsset({ asset: 'hero' }, { rpc: UNUSED, dialogs });
  assert.deepEqual(res, { ok: false, cancelled: true });
});

test('exportAsset: explicit output skips the dialog entirely', async () => {
  const rpc = makeRpc(async () => ({ ok: true, result: atlasSuccessResult() }));
  const dialogs = {
    chooseExportDir: async () => {
      throw new Error('must not be called when output is supplied directly');
    },
  };
  const res = await exportAsset({ asset: 'hero', output: 'C:\\out' }, { rpc, dialogs });
  assert.equal(res.ok, true);
  assert.equal(rpc.calls[0].params.output, 'C:\\out');
});

// ---------------------------------------------------------------------------
// Success
// ---------------------------------------------------------------------------

test('exportAsset: success calls export.apply with "output" (not "destination"/"dir") and hoists fields', async () => {
  const rpc = makeRpc(async (method, params) => {
    assert.equal(method, 'export.apply');
    assert.equal(params.asset, 'hero');
    assert.equal(params.output, 'C:\\out');
    assert.equal('destination' in params, false);
    assert.equal('dir' in params, false);
    return { ok: true, result: atlasSuccessResult() };
  });
  const dialogs = { chooseExportDir: async () => 'C:\\out' };

  const res = await exportAsset({ asset: 'hero' }, { rpc, dialogs });
  assert.equal(res.ok, true);
  assert.equal(res.asset, 'hero');
  assert.equal(res.directory, 'C:\\out');
  assert.deepEqual(res.files, [
    { name: 'chouko.json', bytes: 512 },
    { name: 'page_0.png', bytes: 331 },
  ]);
  assert.equal(res.revision, 2);
  assert.equal(res.format, 'generic-json');
  assert.deepEqual(res.warnings, []);
  assert.deepEqual(res.metrics, { pages: 1, fill_ratio: 0.42 });
  assert.deepEqual(res.result, atlasSuccessResult());
});

test('exportAsset: frames format success round-trips one PNG per frame', async () => {
  const framesResult = {
    asset: 'hero',
    format: 'frames',
    directory: 'C:\\out',
    files: [
      { name: 'f0.png', bytes: 214 },
      { name: 'f1.png', bytes: 219 },
    ],
    revision: 2,
    warnings: [],
    metrics: {},
  };
  const rpc = makeRpc(async (_method, params) => {
    assert.equal(params.format, 'frames');
    return { ok: true, result: framesResult };
  });
  const dialogs = { chooseExportDir: async () => 'C:\\out' };

  const res = await exportAsset({ asset: 'hero', format: 'frames', output: 'C:\\out' }, { rpc, dialogs });
  assert.equal(res.ok, true);
  assert.equal(res.format, 'frames');
  assert.deepEqual(res.files, framesResult.files);
});

test('exportAsset: optional atlas/pack params are only forwarded when the caller supplies them', async () => {
  const rpc = makeRpc(async (_method, params) => {
    assert.deepEqual(Object.keys(params).sort(), ['asset', 'output']);
    return { ok: true, result: atlasSuccessResult() };
  });
  await exportAsset({ asset: 'hero', output: 'C:\\out' }, { rpc, dialogs: UNUSED });

  const rpc2 = makeRpc(async (_method, params) => {
    assert.equal(params.layout, 'horizontal');
    assert.equal(params.columns, 2);
    assert.equal(params.padding, 2);
    assert.equal(params.extrude, 1);
    assert.equal(params.trim, true);
    assert.equal(params.maxSize, '512x512');
    assert.equal(params.multiPage, false);
    assert.equal(params.name, 'chouko');
    assert.equal(params.overwrite, false);
    return { ok: true, result: atlasSuccessResult() };
  });
  await exportAsset(
    {
      asset: 'hero',
      output: 'C:\\out',
      name: 'chouko',
      overwrite: false,
      layout: 'horizontal',
      columns: 2,
      padding: 2,
      extrude: 1,
      trim: true,
      maxSize: '512x512',
      multiPage: false,
    },
    { rpc: rpc2, dialogs: UNUSED },
  );
});

// ---------------------------------------------------------------------------
// RPC errors passed through unchanged
// ---------------------------------------------------------------------------

test('exportAsset: overwrite rejection (code 7) from export.apply is surfaced unchanged', async () => {
  const rpcError = { code: 7, message: 'target exists, pass overwrite=true' };
  const rpc = makeRpc(async () => ({ ok: false, error: rpcError }));
  const dialogs = { chooseExportDir: async () => 'C:\\out' };

  const res = await exportAsset({ asset: 'hero' }, { rpc, dialogs });
  assert.equal(res.ok, false);
  assert.equal(res.cancelled, undefined);
  assert.deepEqual(res.error, rpcError);
});

test('exportAsset: overwrite=true is forwarded so a second call can proceed past the code-7 refusal', async () => {
  let calls = 0;
  const rpc = makeRpc(async (_method, params) => {
    calls += 1;
    if (calls === 1) {
      return { ok: false, error: { code: 7, message: 'target exists, pass overwrite=true' } };
    }
    assert.equal(params.overwrite, true);
    return { ok: true, result: atlasSuccessResult() };
  });
  const dialogs = { chooseExportDir: async () => 'C:\\out' };

  const first = await exportAsset({ asset: 'hero' }, { rpc, dialogs });
  assert.equal(first.ok, false);
  assert.equal(first.error.code, 7);

  const second = await exportAsset({ asset: 'hero', overwrite: true }, { rpc, dialogs });
  assert.equal(second.ok, true);
  assert.equal(rpc.calls.length, 2);
});

test('exportAsset: no-project rejection (code 3) from export.apply is surfaced unchanged', async () => {
  const rpcError = { code: 3, message: 'no project is open' };
  const rpc = makeRpc(async () => ({ ok: false, error: rpcError }));
  const dialogs = { chooseExportDir: async () => 'C:\\out' };

  const res = await exportAsset({ asset: 'hero' }, { rpc, dialogs });
  assert.equal(res.ok, false);
  assert.deepEqual(res.error, rpcError);
});

test('exportAsset: unknown-asset rejection (code 3) from export.apply is surfaced unchanged', async () => {
  const rpcError = { code: 3, message: 'asset not found' };
  const rpc = makeRpc(async () => ({ ok: false, error: rpcError }));
  const dialogs = { chooseExportDir: async () => 'C:\\out' };

  const res = await exportAsset({ asset: 'nope' }, { rpc, dialogs });
  assert.equal(res.ok, false);
  assert.deepEqual(res.error, rpcError);
});

test('exportAsset: empty-frame-set rejection (code 2) from export.apply is surfaced unchanged', async () => {
  const rpcError = { code: 2, message: 'asset has no frames to export' };
  const rpc = makeRpc(async () => ({ ok: false, error: rpcError }));
  const dialogs = { chooseExportDir: async () => 'C:\\out' };

  const res = await exportAsset({ asset: 'empty' }, { rpc, dialogs });
  assert.equal(res.ok, false);
  assert.deepEqual(res.error, rpcError);
});

// ---------------------------------------------------------------------------
// Paths with spaces / non-ASCII characters
// ---------------------------------------------------------------------------

test('exportAsset: an output directory with spaces is forwarded byte-for-byte', async () => {
  const spacedPath = 'C:\\Users\\Some User\\My Exports\\hero atlas';
  const rpc = makeRpc(async (_method, params) => {
    assert.equal(params.output, spacedPath);
    return { ok: true, result: atlasSuccessResult({ directory: spacedPath }) };
  });
  const dialogs = { chooseExportDir: async () => spacedPath };

  const res = await exportAsset({ asset: 'hero' }, { rpc, dialogs });
  assert.equal(res.ok, true);
  assert.equal(res.directory, spacedPath);
});

test('exportAsset: an output directory with Chinese characters is forwarded byte-for-byte', async () => {
  const cjkPath = 'C:\\用户\\项目\\导出目录';
  const rpc = makeRpc(async (_method, params) => {
    assert.equal(params.output, cjkPath);
    return { ok: true, result: atlasSuccessResult({ directory: cjkPath }) };
  });
  const dialogs = { chooseExportDir: async () => cjkPath };

  const res = await exportAsset({ asset: 'hero' }, { rpc, dialogs });
  assert.equal(res.ok, true);
  assert.equal(res.directory, cjkPath);
});

test('exportAsset: an explicit (non-dialog) output with spaces and Chinese characters round-trips too', async () => {
  const mixedPath = 'D:\\我的 导出 目录\\hero exports';
  const rpc = makeRpc(async (_method, params) => {
    assert.equal(params.output, mixedPath);
    return { ok: true, result: atlasSuccessResult({ directory: mixedPath }) };
  });
  const res = await exportAsset({ asset: 'hero', output: mixedPath }, { rpc, dialogs: UNUSED });
  assert.equal(res.ok, true);
  assert.equal(res.directory, mixedPath);
});

test('exportAsset: module must not cache or dedupe across calls (fresh rpc call every time)', async () => {
  const rpc = makeRpc(async () => ({ ok: true, result: atlasSuccessResult() }));
  const dialogs = { chooseExportDir: async () => 'C:\\out' };

  await exportAsset({ asset: 'hero' }, { rpc, dialogs });
  await exportAsset({ asset: 'hero' }, { rpc, dialogs });
  assert.equal(rpc.calls.length, 2);
});
