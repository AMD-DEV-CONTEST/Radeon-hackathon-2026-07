import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/api_client.dart';
import 'api_provider.dart';
import 'settings_provider.dart';

enum ModelLoadStatus { idle, loading, loaded, error }

class ModelLoadState {
  final ModelLoadStatus status;
  final String? error;
  const ModelLoadState({this.status = ModelLoadStatus.idle, this.error});
}

/// Drives the model picker in the bottom chat toolbar: picking a model both
/// persists it (POST /api/settings, same as before) AND eagerly loads it
/// into VRAM (POST /api/vte/warmup) so the picker can show real "carregando
/// modelo" feedback -- /api/settings alone never touched VRAM, it only
/// saved a preference VTE would lazily apply on the next chat turn.
class ModelLoadNotifier extends StateNotifier<ModelLoadState> {
  final ApiClient _api;
  final Ref _ref;
  ModelLoadNotifier(this._api, this._ref) : super(const ModelLoadState());

  Future<void> selectModel(String model) async {
    state = const ModelLoadState(status: ModelLoadStatus.loading);
    try {
      final settings = _ref.read(settingsProvider).valueOrNull;
      await _api.saveSettings(model, contextLength: settings?.contextLength);
      await _api.warmupModel(model);
      await _ref.read(settingsProvider.notifier).refresh();
      state = const ModelLoadState(status: ModelLoadStatus.loaded);
    } on ApiException catch (e) {
      state = ModelLoadState(status: ModelLoadStatus.error, error: e.message);
    } catch (e) {
      state = ModelLoadState(status: ModelLoadStatus.error, error: e.toString());
    }
  }

  /// VTE's real context window (see vte_bridge.py's module docstring): sized
  /// into the KV cache at model-load time, so changing it needs the exact
  /// same persist-then-reload dance as selectModel, not a per-request
  /// field. Reuses the same ModelLoadState the model picker already drives,
  /// so the toolbar's loading feedback is consistent for either control.
  Future<void> changeContextLength(int contextLength) async {
    final currentModel = _ref.read(settingsProvider).valueOrNull?.defaultModel;
    if (currentModel == null || currentModel.isEmpty) return;
    state = const ModelLoadState(status: ModelLoadStatus.loading);
    try {
      await _api.saveSettings(currentModel, contextLength: contextLength);
      await _api.warmupModel(currentModel);
      await _ref.read(settingsProvider.notifier).refresh();
      state = const ModelLoadState(status: ModelLoadStatus.loaded);
    } on ApiException catch (e) {
      state = ModelLoadState(status: ModelLoadStatus.error, error: e.message);
    } catch (e) {
      state = ModelLoadState(status: ModelLoadStatus.error, error: e.toString());
    }
  }
}

/// Auto-warmup on boot: previously VTE only loaded into VRAM when the user
/// opened the model picker and explicitly chose one -- the very first chat
/// message on a fresh launch always paid the full model-load latency
/// inline, with nothing telling the user why the app seemed to hang.
/// `settingsProvider` already fetches `default_model` once on boot (see its
/// own `tokenReadyProvider` listener, which fires during `_Bootstrap` --
/// well before login, since it only depends on the backend being reachable,
/// not on who's using it). The moment that data is available, kick off the
/// same `selectModel()` warmup path the picker uses.
///
/// `fireImmediately: true` matters here, not just style: `settingsProvider`
/// has very likely *already* resolved by the time anything first reads
/// `modelLoadProvider` (Riverpod providers are lazy, and nothing touches
/// this one until MainScreen mounts, i.e. after the user logs in -- well
/// after settings loaded). Without it, `ref.listen` only reacts to CHANGES
/// after this point, and a value that arrived in the past never re-fires --
/// the warmup would silently never trigger. The `idle` guard still blocks
/// the immediate call from double-firing against the re-entrant refresh
/// `selectModel` triggers on completion (state is `loading` by then).
final StateNotifierProvider<ModelLoadNotifier, ModelLoadState> modelLoadProvider =
    StateNotifierProvider<ModelLoadNotifier, ModelLoadState>((ref) {
  final notifier = ModelLoadNotifier(ref.watch(apiClientProvider), ref);
  ref.listen(settingsProvider, (previous, next) {
    final model = next.asData?.value.defaultModel ?? '';
    // notifier.state, not ref.read(modelLoadProvider): reading a provider
    // from inside its own builder/listener trips Riverpod's
    // _debugAssertCanDependOn guard against self-referential dependencies
    // and crashes at runtime in debug mode (confirmed directly -- this is
    // not a hypothetical). `notifier` is the same object modelLoadProvider
    // will expose once construction finishes, so reading its `state` here
    // is exactly the value ref.read(modelLoadProvider) would have
    // returned, without going through the provider-dependency graph that
    // triggers the assertion.
    // ignore: invalid_use_of_protected_member, invalid_use_of_visible_for_testing_member
    if (model.isNotEmpty && notifier.state.status == ModelLoadStatus.idle) {
      notifier.selectModel(model);
    }
  }, fireImmediately: true);
  return notifier;
});

/// VTE's real context window (prompt + response), persisted server-side and
/// read directly off settingsProvider rather than mirrored into a separate
/// client-side StateProvider -- there's nothing to desync that way. Display
/// value: `ref.watch(settingsProvider).valueOrNull?.contextLength ?? 2048`;
/// to change it, call `modelLoadProvider.notifier.changeContextLength(v)`,
/// which persists it and reloads the model (see that method's doc).
const contextLengthOptions = [512, 1024, 2048, 4096, 8192];

/// Client-side only, never sent to /api/settings: bounds `max_tokens` on
/// the next chat turn (how long/thorough a reply is allowed to be), a
/// completely different knob from contextLengthOptions above (the model's
/// total prompt+response capacity, fixed at load time). A smaller budget
/// finishes generating sooner; a larger one lets the model reason through
/// more before answering -- hence "Faster" vs "Smarter" in the picker, not
/// "more/less context".
final intelligenceProvider = StateProvider<int>((ref) => 4096);

const intelligenceOptions = [512, 1024, 2048, 4096, 8192];
