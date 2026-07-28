import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/api_client.dart';
import '../data/models/app_state_models.dart';
import 'api_provider.dart';

class SettingsNotifier extends StateNotifier<AsyncValue<SettingsState>> {
  final ApiClient _api;
  SettingsNotifier(this._api) : super(const AsyncValue.loading());

  Future<void> refresh() async {
    state = const AsyncValue.loading();
    try {
      final json = await _api.getSettings();
      state = AsyncValue.data(SettingsState.fromJson(json));
    } catch (e, st) {
      state = AsyncValue.error(e, st);
    }
  }

  /// Returns null on success, or a user-facing error message (mirrors
  /// `chat_controller.py::save_default_model`'s bool but with the reason).
  Future<String?> saveDefaultModel(String model) async {
    try {
      await _api.saveSettings(model);
      await refresh();
      return null;
    } on ApiException catch (e) {
      return e.message;
    } catch (e) {
      return e.toString();
    }
  }
}

final settingsProvider =
    StateNotifierProvider<SettingsNotifier, AsyncValue<SettingsState>>((ref) {
  final notifier = SettingsNotifier(ref.watch(apiClientProvider));
  ref.watch(tokenReadyProvider).whenData((_) => notifier.refresh());
  return notifier;
});
