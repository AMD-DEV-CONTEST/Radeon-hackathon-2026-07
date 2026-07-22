import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_provider.dart';

class CartographerState {
  final int mapped;
  final int total;
  final String state; // "idle" | "mapping" | "paused"

  const CartographerState({this.mapped = 0, this.total = 0, this.state = 'idle'});

  factory CartographerState.fromJson(Map<String, dynamic> json) {
    return CartographerState(
      mapped: json['mapped'] as int? ?? 0,
      total: json['total'] as int? ?? 0,
      state: json['state']?.toString() ?? 'idle',
    );
  }

  bool get inProgress => total > 0 && mapped < total;
}

/// Polls GET /api/cartographer/status for the title bar's discreet
/// mapping-progress badge (Fase D) -- same polling shape as
/// telemetryProvider/egressProvider.
final cartographerProvider = StreamProvider<CartographerState>((ref) async* {
  await ref.watch(tokenReadyProvider.future);
  final api = ref.watch(apiClientProvider);
  while (true) {
    try {
      final json = await api.cartographerStatus();
      yield CartographerState.fromJson(json);
    } catch (_) {
      yield const CartographerState();
    }
    await Future.delayed(const Duration(seconds: 4));
  }
});
