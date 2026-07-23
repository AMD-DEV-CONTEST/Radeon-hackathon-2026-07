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
  Future<String?> select(String path, {String? chatId}) async {
    try {
      final json = await _api.setProjectPath(path, chatId: chatId);
      state = AsyncValue.data(json['path']?.toString() ?? path);
      return null;
    } on ApiException catch (e) {
      return e.message;
    } catch (e) {
      return e.toString();
    }
  }

  /// Called on switching to a different chat: looks up what THAT chat last
  /// had open and, if it's set and differs from what's currently active,
  /// re-applies it -- so each chat keeps its own project across switches
  /// instead of silently inheriting whatever another chat left active.
  /// A chat that's never had a project set is left alone (no-op), same as
  /// today's behavior before this existed.
  Future<void> restoreForChat(String chatId) async {
    try {
      final remembered = await _api.getProjectPathForChat(chatId);
      if (remembered.isEmpty) return;
      final current = state.valueOrNull ?? '';
      if (remembered == current) return;
      await select(remembered, chatId: chatId);
    } catch (_) {
      // Best-effort: a failed lookup just leaves the current project as-is,
      // same as if this feature didn't exist.
    }
  }
}

final projectPathProvider = StateNotifierProvider<ProjectPathNotifier, AsyncValue<String>>((ref) {
  final notifier = ProjectPathNotifier(ref.watch(apiClientProvider));
  ref.watch(tokenReadyProvider).whenData((_) => notifier.refresh());
  return notifier;
});
