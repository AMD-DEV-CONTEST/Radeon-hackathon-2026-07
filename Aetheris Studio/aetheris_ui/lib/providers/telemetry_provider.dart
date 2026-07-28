import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/models/app_state_models.dart';
import 'api_provider.dart';

/// Polls GET /api/telemetry for the status-bar footer. Shorter interval
/// than healthProvider's 15s: tok/s and VRAM are meant to feel live while
/// a generation is in flight, not just periodically refreshed.
final telemetryProvider = StreamProvider<TelemetryState>((ref) async* {
  await ref.watch(tokenReadyProvider.future);
  final api = ref.watch(apiClientProvider);
  while (true) {
    try {
      final json = await api.telemetry();
      yield TelemetryState.fromJson(json);
    } catch (_) {
      yield const TelemetryState();
    }
    await Future.delayed(const Duration(seconds: 3));
  }
});
