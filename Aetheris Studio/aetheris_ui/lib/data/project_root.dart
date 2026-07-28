import 'dart:io';

/// Locates the Aetheris Studio project root (the folder containing `app.py`
/// and `.env`) by walking up from wherever this client is actually running
/// -- dev `flutter run` (cwd = aetheris_ui/) or the built .exe copied
/// anywhere under the project (see BackendLauncher). Shared by EnvLoader
/// (finds `.env`) and BackendLauncher (finds `app.py` + `.venv`).
class ProjectRoot {
  static Future<Directory?> find({required bool Function(Directory dir) isRoot}) async {
    final candidates = <Directory>[
      Directory.current,
      File(Platform.resolvedExecutable).parent,
    ];

    for (final start in candidates) {
      var dir = start;
      for (var i = 0; i < 10; i++) {
        if (isRoot(dir)) return dir;
        final parent = dir.parent;
        if (parent.path == dir.path) break;
        dir = parent;
      }
    }
    return null;
  }

  static Future<Directory?> findAetherisRoot() {
    return find(isRoot: (dir) => File('${dir.path}${Platform.pathSeparator}app.py').existsSync());
  }
}
