import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/api_client.dart';
import '../data/models/app_state_models.dart';
import 'api_provider.dart';

class AuthNotifier extends StateNotifier<AsyncValue<AuthState>> {
  final ApiClient _api;
  AuthNotifier(this._api) : super(const AsyncValue.loading());

  Future<void> refresh() async {
    state = const AsyncValue.loading();
    try {
      final json = await _api.authStatus();
      state = AsyncValue.data(AuthState.fromJson(json));
    } catch (e, st) {
      state = AsyncValue.error(e, st);
    }
  }

  /// Returns null on success, or a user-facing error message. Handles 401
  /// (bad credentials) and 429 (rate limited, 5/60s server-side) the same
  /// way `chat_controller.py::login` did.
  Future<String?> login(String username, String password) async {
    try {
      final json = await _api.login(username, password);
      state = AsyncValue.data(AuthState(configured: true, username: json['username']?.toString()));
      return null;
    } on ApiException catch (e) {
      if (e.statusCode == 429) return 'Muitas tentativas. Aguarde um minuto.';
      if (e.statusCode == 401) return 'Usuário ou senha inválidos.';
      return e.message;
    } catch (e) {
      return e.toString();
    }
  }
}

final authProvider = StateNotifierProvider<AuthNotifier, AsyncValue<AuthState>>((ref) {
  final notifier = AuthNotifier(ref.watch(apiClientProvider));
  ref.watch(tokenReadyProvider).whenData((_) => notifier.refresh());
  return notifier;
});
