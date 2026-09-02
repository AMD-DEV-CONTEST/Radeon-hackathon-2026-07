/// tauri-globals.d.ts
/// Tells TypeScript that `window.__TAURI_INTERNALS__` is a valid property
/// when running inside the Tauri desktop shell. The `invoke` function and
/// all other Tauri APIs are only present when this sentinel is defined.

interface Window {
  /**
   * Injected by Tauri's webview bootstrap script.
   * Present only when the app is running inside the Tauri shell.
   * Undefined in a standard browser context.
   */
  __TAURI_INTERNALS__?: Record<string, unknown>;
}
