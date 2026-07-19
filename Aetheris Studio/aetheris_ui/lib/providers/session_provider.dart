import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Whether the user has successfully logged in *this app session* (client
/// side only -- the backend has no session/cookie mechanism, `X-Internal-
/// Token` already gates every API call regardless of login state). This
/// just drives which screen `main.dart` shows: a login gate, like
/// Claude.ai/ChatGPT show before their app shell, rather than burying auth
/// inside a settings dialog.
final isAuthenticatedProvider = StateProvider<bool>((ref) => false);
