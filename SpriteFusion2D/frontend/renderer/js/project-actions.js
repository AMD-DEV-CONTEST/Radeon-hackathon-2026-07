// Deep module for the "New Project" and "Import Asset" flows (Luna task E02).
//
// Design constraints (docs/luna-workpack/PROMPTS_IMPLEMENTATION.md, task E02):
//  - No Electron, DOM or global `window` access. Everything this module needs
//    (RPC transport, native file/folder pickers) is passed in by the caller
//    on every call. That keeps it runnable under plain `node --test` with
//    mocks, and reusable once E01's real dialogs land.
//  - No toasts and no other UI side effects. Callers (E03) turn the returned
//    result into UI feedback.
//  - Deterministic: `deriveSafeId` always returns the same id for the same
//    input. No randomness, no timestamps, no hidden module state.
//
// Public interface (exactly three functions, per the E02 brief):
//   - deriveSafeId(name, options?) -> string
//   - createProject(input, deps)   -> Promise<Result>
//   - importAsset(input, deps)     -> Promise<Result>
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
// `dialogs` - object with the two pickers this module needs:
//   - `chooseProjectParent() => Promise<string|null>` - directory that will
//     hold the new project folder. `null` means the user cancelled.
//   - `chooseImportImage()   => Promise<string|null>` - image file to
//     import. `null` means the user cancelled.
//   Both are optional inputs: pass `parentDir` / `path` directly in the
//   input object (e.g. for drag & drop) to skip the matching picker, and the
//   matching `dialogs` method is then never called.
//
// ---------------------------------------------------------------------------
// Result shape
// ---------------------------------------------------------------------------
//
// Every public async method resolves (never rejects on expected failure
// paths) to one of:
//   - `{ ok: false, cancelled: true }`
//       The user cancelled a picker. Callers should not show an error.
//   - `{ ok: false, error: { code, message, ... } }`
//       Either a local validation failure (`code: 2`, the same shape as the
//       backend's `UsageError`) or the `error` object `rpc.call()` produced,
//       passed through unchanged. Callers should show the unified toast.
//   - `{ ok: true, ... }`
//       See `createProject` / `importAsset` below for the exact fields.

const ID_PATTERN = /^[a-z0-9_]+$/;
const MAX_ID_LENGTH = 48;
const MAX_NAME_LENGTH = 120;
const DEFAULT_FALLBACK_PREFIX = 'project';

/**
 * Turn arbitrary display text (including Chinese names) into a stable id
 * that satisfies the backend's `ID_PATTERN` (`^[a-z0-9_]+$`,
 * `sprite_workshop/ids.py`). Used both for the new project's `project_id`
 * and, when a picked file has a non-ASCII stem, for `asset.import`'s `as`.
 *
 * Pure and deterministic: same `rawText` in, same id out, every time.
 *
 * @param {string} rawText
 * @param {{ fallbackPrefix?: string }} [options]
 * @returns {string}
 */
export function deriveSafeId(rawText, options = {}) {
  const fallbackPrefix = options.fallbackPrefix || DEFAULT_FALLBACK_PREFIX;
  const source = typeof rawText === 'string' ? rawText : '';
  const trimmed = source.trim();

  let slug = trimmed
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '');

  if (slug.length > MAX_ID_LENGTH) {
    slug = slug.slice(0, MAX_ID_LENGTH).replace(/^_+|_+$/g, '');
  }

  // Nothing ASCII-alnum survived (e.g. an all-Chinese name, or a name made
  // only of punctuation): fall back to a stable hash of the original text
  // instead of transliterating behind the user's back.
  if (!slug || !ID_PATTERN.test(slug)) {
    slug = `${fallbackPrefix}_${stableHash(trimmed || fallbackPrefix)}`;
  }

  return slug;
}

/**
 * Validate a project name and create the project via `project.create`.
 *
 * @param {{ name: string, id?: string, parentDir?: string }} input
 *   `name` is the human-facing project name (Chinese is fine).
 *   `id` optionally overrides the derived id; it is validated as-is and
 *   never falls back automatically (a bad explicit id is a caller bug).
 *   `parentDir` optionally supplies the directory to create the project in,
 *   skipping `dialogs.chooseProjectParent()`.
 * @param {{ rpc: object, dialogs: object }} deps
 * @returns {Promise<
 *   { ok: false, cancelled: true } |
 *   { ok: false, error: object } |
 *   { ok: true, id: string, path: string, project: object }
 * >}
 *   On success, `project` is `project.create`'s result (which itself is the
 *   `project.open` shape: `project_id`, `name`, `path`, `schema_version`,
 *   `head_revision`, `defaults`).
 */
export async function createProject(input = {}, deps = {}) {
  const { rpc, dialogs } = deps;
  const nameError = validateProjectName(input.name);
  if (nameError) {
    return { ok: false, error: nameError };
  }
  const name = input.name.trim();

  let id = input.id;
  if (id) {
    if (!ID_PATTERN.test(id)) {
      return {
        ok: false,
        error: {
          code: 2,
          message: 'project id may only contain lowercase letters, digits and underscore',
          value: id,
        },
      };
    }
  } else {
    id = deriveSafeId(name);
  }

  let parentDir = input.parentDir;
  if (!parentDir) {
    parentDir = await dialogs.chooseProjectParent();
    if (!parentDir) {
      return { ok: false, cancelled: true };
    }
  }

  const path = joinPath(parentDir, id);
  const reply = await rpc.call('project.create', { path, id, name });
  if (!reply.ok) {
    return { ok: false, error: reply.error };
  }

  return { ok: true, id, path, project: reply.result };
}

/**
 * Pick (or accept) an image file and import it via `asset.import`.
 *
 * @param {{ path?: string, as?: string }} input
 *   `path` optionally supplies the source file path directly, skipping
 *   `dialogs.chooseImportImage()`.
 *   `as` optionally overrides the imported source's name; it is validated
 *   as-is. When omitted, the name is derived from the file's stem via
 *   `deriveSafeId`, so non-ASCII filenames still import cleanly.
 * @param {{ rpc: object, dialogs: object }} deps
 * @returns {Promise<
 *   { ok: false, cancelled: true } |
 *   { ok: false, error: object } |
 *   { ok: true, asset: string, path: string, revision: number, result: object }
 * >}
 *   On success, `result` is `asset.import`'s raw reply
 *   (`{ asset, kind, revision }`); `asset`/`revision` are hoisted for
 *   convenience.
 */
export async function importAsset(input = {}, deps = {}) {
  const { rpc, dialogs } = deps;

  let path = input.path;
  if (!path) {
    path = await dialogs.chooseImportImage();
    if (!path) {
      return { ok: false, cancelled: true };
    }
  }

  let as = input.as;
  if (as) {
    if (!ID_PATTERN.test(as)) {
      return {
        ok: false,
        error: {
          code: 2,
          message: 'asset name may only contain lowercase letters, digits and underscore',
          value: as,
        },
      };
    }
  } else {
    as = deriveSafeId(stemFromPath(path), { fallbackPrefix: 'asset' });
  }

  const reply = await rpc.call('asset.import', { path, as });
  if (!reply.ok) {
    return { ok: false, error: reply.error };
  }

  return {
    ok: true,
    asset: reply.result.asset,
    path,
    revision: reply.result.revision,
    result: reply.result,
  };
}

// ---------------------------------------------------------------------------
// Internal helpers (not exported; keep the public surface at three methods)
// ---------------------------------------------------------------------------

function validateProjectName(name) {
  if (typeof name !== 'string' || !name.trim()) {
    return { code: 2, message: 'project name is required' };
  }
  if (name.trim().length > MAX_NAME_LENGTH) {
    return {
      code: 2,
      message: `project name must be at most ${MAX_NAME_LENGTH} characters`,
      value: name,
    };
  }
  return null;
}

// A small, dependency-free deterministic string hash (browser + Node safe;
// this module must not import Node builtins such as `crypto` because it
// runs in a contextIsolated renderer with no Node integration). Good enough
// for producing a stable filesystem-safe suffix, not for security.
function stableHash(text) {
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = (Math.imul(hash, 31) + text.charCodeAt(i)) >>> 0;
  }
  return hash.toString(36);
}

// Join a directory and a child name without Node's `path` module (also
// unavailable in the renderer). The Python backend parses the result with
// `pathlib.Path`, which accepts forward slashes on every platform.
function joinPath(parentDir, child) {
  const trimmed = String(parentDir).replace(/[\\/]+$/, '');
  return `${trimmed}/${child}`;
}

// Extract a file's stem (basename without extension) without Node's `path`
// module. Handles both `/` and `\` separators since the picked path may
// come from any OS.
function stemFromPath(rawPath) {
  const normalized = String(rawPath).replace(/\\/g, '/');
  const base = normalized.split('/').pop() || normalized;
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(0, dot) : base;
}
