import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/api_client.dart';
import 'api_provider.dart';

/// Tracks the active project folder (Fase 4.5: ported from Flet's
/// `chat_controller.py::set_project_path`, now a real backend endpoint
/// since Flutter and the backend are separate processes -- see
/// `core/utils/project_path.py`).
class ProjectPathNotifier extends StateNotifier<AsyncValue<String>> {
  final ApiClient _api;
  ProjectPathNotifier(this._api) : super(const AsyncValue.data(''));

  Future<void> refresh() async {
    try {
      final json = await _api.getProjectPath();
      state = AsyncValue.data(json['path']?.toString() ?? '');
    } catch (e, st) {
      state = AsyncValue.error(e, st);
    }
  }

  /// Returns null on success, or a user-facing error message.
  Future<String?> select(String path) async {
    try {
      final json = await _api.setProjectPath(path);
      state = AsyncValue.data(json['path']?.toString() ?? path);
      return null;
    } on ApiException catch (e) {
      return e.message;
    } catch (e) {
      return e.toString();
    }
  }
}

final projectPathProvider = StateNotifierProvider<ProjectPathNotifier, AsyncValue<String>>((ref) {
  final notifier = ProjectPathNotifier(ref.watch(apiClientProvider));
  ref.watch(tokenReadyProvider).whenData((_) => notifier.refresh());
  return notifier;
});
