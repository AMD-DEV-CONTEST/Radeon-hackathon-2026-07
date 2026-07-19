import 'dart:io';

import 'project_root.dart';

/// Locates the shared `.env` file the Python backend (app.py) reads/writes
/// AETHERIS_INTERNAL_TOKEN into, and reads that token. The backend and this
/// Flutter client are two processes on the same desktop machine sharing one
/// project checkout -- there's no login handshake for this token, it's a
/// local file secret, so we look for it the same way `chat_controller.py`
/// did, via [ProjectRoot].
class EnvLoader {
  static const _key = 'AETHERIS_INTERNAL_TOKEN';

  static Future<String?> loadInternalToken() async {
    final root = await ProjectRoot.find(
      isRoot: (dir) => File('${dir.path}${Platform.pathSeparator}.env').existsSync(),
    );
    if (root == null) return null;
    return _extractToken(File('${root.path}${Platform.pathSeparator}.env'));
  }

  static Future<String?> _extractToken(File envFile) async {
    final lines = await envFile.readAsLines();
    for (final line in lines) {
      final trimmed = line.trim();
      if (trimmed.startsWith('$_key=')) {
        var value = trimmed.substring(_key.length + 1);
        if (value.length >= 2 &&
            ((value.startsWith('"') && value.endsWith('"')) ||
                (value.startsWith("'") && value.endsWith("'")))) {
          value = value.substring(1, value.length - 1);
        }
        return value.isEmpty ? null : value;
      }
    }
    return null;
  }
}
