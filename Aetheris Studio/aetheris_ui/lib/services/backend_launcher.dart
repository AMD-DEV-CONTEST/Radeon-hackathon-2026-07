import 'dart:io';

import '../data/project_root.dart';

/// Ensures the Python FastAPI backend (app.py) is running before the app
/// shows any UI. Flips the old launch direction: `app.py` used to spawn the
/// Flet GUI as its own child process on startup (`_launch_flet_gui()` in
/// app.py); now this Flutter client is the thing users double-click, so IT
/// is responsible for making sure the backend exists, the same way
/// Claude Desktop/VS Code ensure their own backend processes are up before
/// showing a window.
class BackendLauncher {
  static const _backendUrl = 'http://127.0.0.1:8001/';
  static const _port = 8001;

  Future<bool> _isBackendAlive() async {
    try {
      final client = HttpClient()
        ..connectionTimeout = const Duration(milliseconds: 800)
        // Rule out the system/Windows proxy (GUI apps can inherit it,
        // terminals/standalone scripts often don't) intercepting loopback
        // traffic and never forwarding it to uvicorn.
        ..findProxy = (uri) => 'DIRECT';
      final req = await client.getUrl(Uri.parse(_backendUrl));
      final res = await req.close().timeout(const Duration(seconds: 4));
      await res.drain();
      client.close();
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Returns true once the backend is confirmed reachable (either it was
  /// already running, or we started it and it came up in time). Returns
  /// false if we couldn't find the project (app.py) or it never came up --
  /// callers should show a clear connection error rather than a blank app.
  Future<bool> ensureRunning() async {
    if (await _isBackendAlive()) return true;

    final root = await ProjectRoot.findAetherisRoot();
    if (root == null) return false;

    final sep = Platform.pathSeparator;
    // pythonw.exe (not python.exe): no console window, and it's spawned as
    // a direct child (ProcessStartMode.detachedWithStdio, no cmd/powershell
    // wrapper), so Task Manager's Processes tab nests it under
    // aetheris_ui.exe like any normal parent/child pair. The earlier
    // "pythonw.exe hangs" finding was the same check_ollama() root cause
    // as everything else in this launcher's history, not a real pythonw
    // problem -- confirmed by retesting after that fix landed.
    final venvPythonw = File('${root.path}$sep.venv${sep}Scripts${sep}pythonw.exe');
    final pythonExe = await venvPythonw.exists() ? venvPythonw.path : 'pythonw';
    final appPy = '${root.path}${sep}app.py';

    try {
      final process = await Process.start(
        pythonExe,
        [appPy],
        workingDirectory: root.path,
        mode: ProcessStartMode.detachedWithStdio,
      );
      process.stdout.listen((_) {});
      process.stderr.listen((_) {});
    } catch (_) {
      return false;
    }

    for (var i = 0; i < 40; i++) {
      await Future.delayed(const Duration(milliseconds: 500));
      if (await _isBackendAlive()) return true;
    }
    return false;
  }

  /// Best-effort graceful shutdown, called unconditionally on window close.
  /// This used to only fire when this client had itself started the backend
  /// (`launchedByUs`), to avoid killing a dev-mode backend started
  /// separately -- but that meant any backend left over from a previous
  /// session (crash, force-quit, a prior launch that set the flag then got
  /// GC'd) could never be reaped by a later session: every later session
  /// would find it already alive, never set the flag, and skip shutdown on
  /// its own close, leaking the VTE model in VRAM indefinitely. This is a
  /// single-user desktop app with no legitimate case for the backend to
  /// outlive the only client that talks to it, so shutdown is now
  /// unconditional -- the only cost is killing a backend a developer started
  /// by hand in a separate terminal for debugging.
  Future<void> shutdown(String internalToken) async {
    try {
      final client = HttpClient()
        ..connectionTimeout = const Duration(seconds: 2)
        ..findProxy = (uri) => 'DIRECT';
      final req = await client.postUrl(Uri.parse('http://127.0.0.1:$_port/api/shutdown'));
      req.headers.set('Content-Type', 'application/json');
      req.headers.set('X-Internal-Token', internalToken);
      req.write('{}');
      await req.close().timeout(const Duration(seconds: 3));
      client.close();
    } catch (_) {}
  }
}
