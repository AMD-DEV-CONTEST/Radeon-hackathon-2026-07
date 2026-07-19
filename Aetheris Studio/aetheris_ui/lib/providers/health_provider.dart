import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/models/app_state_models.dart';
import 'api_provider.dart';

/// Polls GET /api/health every 15s -- same interval as
/// `chat_controller.py::poll_health`'s loop.
final healthProvider = StreamProvider<HealthState>((ref) async* {
  await ref.watch(tokenReadyProvider.future);
  final api = ref.watch(apiClientProvider);
  while (true) {
    try {
      final json = await api.health();
      yield HealthState.fromJson(json);
    } catch (_) {
      yield const HealthState();
    }
    await Future.delayed(const Duration(seconds: 15));
  }
});
