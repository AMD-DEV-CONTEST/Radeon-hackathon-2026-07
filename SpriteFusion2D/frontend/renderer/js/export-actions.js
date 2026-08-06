// Deep module for the "Export" flow (Luna task E04).
//
// Design constraints (docs/luna-workpack/PROMPTS_IMPLEMENTATION.md, task E04):
//  - No Electron, DOM or global `window` access. Everything this module
//    needs (RPC transport, the export-directory picker) is passed in by the
//    caller on every call, so it runs under plain `node --test` with mocks
//    and is reusable once E05 wires it into the real renderer.
//  - No toasts and no other UI side effects. Callers (E05) turn the
//    returned result into UI feedback.
//  - No file/path assembly and no CLI invocation here. The backend's
//    `export.apply` RPC (`sprite_workshop/daemon.py::Daemon.export_apply`,
//    delegating to the `sprite_workshop.export` deep module) does all of
//    that; this module only validates the handful of things worth failing
//    fast on locally and forwards the rest untouched.
//
// Public interface (one function, per the E04 brief):
//   - exportAsset(input, deps) -> Promise<Result>
//
// ---------------------------------------------------------------------------
// Injected dependencies
// ---------------------------------------------------------------------------
//
// `rpc` - object with `call(method, params) => Promise<RpcReply>`, where
//   `RpcReply` is `{ ok: true, result } | { ok: false, error }`. This is the
//   same contract `frontend/renderer/js/rpc.js`'s `rpc.call()` already
//   implements, so the real renderer can pass `rpc` straight through.
//
// `dialogs` - object with the one picker this module needs:
//   - `chooseExportDir() => Promise<string|null>` - directory to export
//     into. `null` means the user cancelled.
//   This name is E04's own choice (mirrors E02's `chooseProjectParent` /
//   `chooseImportImage` naming), not E01's `window.workshop.exportDirDialog`.
//   E05 must adapt: `{ chooseExportDir: () => window.workshop.exportDirDialog() }`
//   (see E02's own note that `project-actions.js`'s `dialogs` shape differs
//   from E01's raw preload names for the same reason).
//   `chooseExportDir` is optional input: pass `output` directly in the input
//   object (e.g. "export again to the same folder") to skip the picker
//   entirely, and `dialogs.chooseExportDir` is then never called.
//
// ---------------------------------------------------------------------------
// Result shape
// ---------------------------------------------------------------------------
//
// `exportAsset` resolves (never rejects on expected failure paths) to one of:
//   - `{ ok: false, cancelled: true }`
//       The user cancelled the export-directory picker. Callers should not
//       show an error.
//   - `{ ok: false, error: { code, message, ... } }`
//       Either a local validation failure (`code: 2`, the same shape as the
//       backend's `UsageError`) or the `error` object `rpc.call()` produced
//       for `export.apply`, passed through unchanged - including
//       `code: 7` "target exists, pass overwrite" rejections. Callers show
//       the unified error toast (see `rpc.js`'s `describeError`); this
//       module never inspects `error.message` strings.
//   - `{ ok: true, asset, directory, files, revision, format, warnings,
//       metrics, result }`
//       `result` is `export.apply`'s raw reply, unmodified. The other
//       fields are hoisted from it for convenience:
//         - `asset`     (string) the exported asset name, echoed back.
//         - `directory` (string) the absolute directory actually written to.
//         - `files`     (Array<{ name: string, bytes: number }>) every file
//                        written (PNG frames, or an atlas JSON + page PNGs).
//         - `revision`  (number) the project's *current* head revision.
//                        Export never writes into the project and never
//                        advances history - this is not a "new" revision,
//                        it is whatever revision was already current. Do
//                        not present it as if export changed project state.
//         - `format`    (string) the format actually used
//                        (`"generic-json"` unless the caller passed
//                        `"frames"`).
//         - `warnings`  (array) non-fatal packer warnings, already
//                        `.to_dict()`-serialized by the backend.
//         - `metrics`   (object) packer metrics (e.g. page count, fill
//                        ratio); empty for `"frames"` format.
//
// ---------------------------------------------------------------------------
// Real `export.apply` response, captured against this repo's
// `tests/test_workshop_export_rpc.py` (Success.test_atlas_export_with_pack_options):
//
//   {
//     "asset": "hero",
//     "format": "generic-json",
//     "directory": "C:\\...\\out",
//     "files": [
//       { "name": "chouko.json", "bytes": 512 },
//       { "name": "page_0.png", "bytes": 331 }
//     ],
//     "revision": 2,
//     "warnings": [],
//     "metrics": { "pages": 1, "fill_ratio": 0.42 }
//   }
//
// and Success.test_frames_export_writes_one_png_per_frame:
//
//   {
//     "asset": "hero",
//     "format": "frames",
//     "directory": "C:\\...\\out",
//     "files": [
//       { "name": "f0.png", "bytes": 214 },
//       { "name": "f1.png", "bytes": 219 }
//     ],
//     "revision": 2,
//     "warnings": [],
//     "metrics": {}
//   }
//
// Field name warning for E05: the RPC param for the export directory is
// **`output`**, not `destination` and not `dir`. This was read directly out
// of `sprite_workshop/daemon.py::Daemon.export_apply`
// (`output = _param_str(params, "output")`, `raise UsageError("missing output")`
// when absent) and confirmed against `tests/test_workshop_export_rpc.py`,
// which calls `export.apply` with `output=str(self.out)` throughout. An
// earlier draft of `docs/luna-workpack/TASK_GRAPH.md` (E04 row) says the
// field is `destination`; that note is wrong/stale - do not follow it.

/**
 * Export one committed asset to a directory via `export.apply`.
 *
 * @param {{
 *   asset: string,
 *   output?: string,
 *   format?: 'frames' | 'generic-json',
 *   name?: string,
 *   overwrite?: boolean,
 *   layout?: string,
 *   columns?: number,
 *   padding?: number,
 *   extrude?: number,
 *   trim?: boolean,
 *   maxSize?: string,
 *   multiPage?: boolean,
 * }} input
 *   `asset` is the committed asset name to export; required.
 *   `output` optionally supplies the export directory directly, skipping
 *   `dialogs.chooseExportDir()`.
 *   `format`/`name`/`overwrite` and the atlas packing options
 *   (`layout`/`columns`/`padding`/`extrude`/`trim`/`maxSize`/`multiPage`)
 *   are forwarded to `export.apply` only when present on `input` - this
 *   module never invents defaults for them and lets the backend's own
 *   defaults apply (`format: "generic-json"`, `name: "atlas"`,
 *   `overwrite: false`, `layout: "compact"`, ...). A default/simple export
 *   UI can omit all of them and just pass `asset` (+ `output` or a picker).
 * @param {{ rpc: object, dialogs: object }} deps
 * @returns {Promise<
 *   { ok: false, cancelled: true } |
 *   { ok: false, error: object } |
 *   { ok: true, asset: string, directory: string, files: Array<{name: string, bytes: number}>,
 *     revision: number, format: string, warnings: array, metrics: object, result: object }
 * >}
 */
export async function exportAsset(input = {}, deps = {}) {
  const { rpc, dialogs } = deps;

  const asset = typeof input.asset === 'string' ? input.asset.trim() : '';
  if (!asset) {
    return { ok: false, error: { code: 2, message: 'asset is required' } };
  }

  // `name`'s traversal/absolute-path rules belong to the backend
  // (`sprite_workshop/export.py::_check_plain_name`) and are already
  // exercised by `tests/test_workshop_export_rpc.py`'s `NameSafety` cases.
  // Duplicating that logic here would risk drifting out of sync with it;
  // a bad `name` simply comes back as an unchanged `code: 2` RPC error.

  let output = input.output;
  if (!output) {
    output = await dialogs.chooseExportDir();
    if (!output) {
      return { ok: false, cancelled: true };
    }
  }

  const params = { asset, output };
  copyIfPresent(input, params, [
    'format',
    'name',
    'overwrite',
    'layout',
    'columns',
    'padding',
    'extrude',
    'trim',
    'maxSize',
    'multiPage',
  ]);

  const reply = await rpc.call('export.apply', params);
  if (!reply.ok) {
    return { ok: false, error: reply.error };
  }

  const result = reply.result;
  return {
    ok: true,
    asset: result.asset,
    directory: result.directory,
    files: result.files,
    revision: result.revision,
    format: result.format,
    warnings: result.warnings,
    metrics: result.metrics,
    result,
  };
}

// ---------------------------------------------------------------------------
// Internal helpers (not exported; keep the public surface at one function)
// ---------------------------------------------------------------------------

// Copy the given keys from `source` to `target` only when actually present
// on `source` (not merely `undefined`-valued), so callers that omit an
// option get the backend's own default instead of an explicit `undefined`.
function copyIfPresent(source, target, keys) {
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(source, key) && source[key] !== undefined) {
      target[key] = source[key];
    }
  }
}
