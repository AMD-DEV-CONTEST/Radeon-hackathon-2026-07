import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_provider.dart';

class EgressState {
  final List<Map<String, dynamic>> externalConnections;
  final int? externalBytes; // null = not measurable (see egress_monitor.py)
  final int loopbackCount;
  final bool sampling;

  const EgressState({
    this.externalConnections = const [],
    this.externalBytes,
    this.loopbackCount = 0,
    this.sampling = false,
  });

  factory EgressState.fromJson(Map<String, dynamic> json) {
    return EgressState(
      externalConnections: (json['external_connections'] as List? ?? []).cast<Map<String, dynamic>>(),
      externalBytes: json['external_bytes'] as int?,
      loopbackCount: json['loopback_count'] as int? ?? 0,
      sampling: json['sampling'] as bool? ?? false,
    );
  }

  bool get isClean => sampling && externalConnections.isEmpty;
}

/// Polls GET /api/egress/status for the "🔒 0 B external" status-footer
/// segment (Blackbox Fase B) -- same StreamProvider polling shape as
/// telemetryProvider, at the same 3s interval, so both live in the footer
/// without one refreshing noticeably out of sync with the other.
final egressProvider = StreamProvider<EgressState>((ref) async* {
  await ref.watch(tokenReadyProvider.future);
  final api = ref.watch(apiClientProvider);
  while (true) {
    try {
      final json = await api.egressStatus();
      yield EgressState.fromJson(json);
    } catch (_) {
      yield const EgressState();
    }
    await Future.delayed(const Duration(seconds: 3));
  }
});
