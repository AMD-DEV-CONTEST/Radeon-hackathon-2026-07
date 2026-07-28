import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/api_client.dart';

final apiClientProvider = Provider<ApiClient>((ref) {
  final client = ApiClient();
  ref.onDispose(client.dispose);
  return client;
});

/// Must complete before any authenticated call -- reads the shared `.env`
/// secret the Python backend also reads. `main.dart` awaits
/// `container.read(tokenReadyProvider.future)` before running the app.
final tokenReadyProvider = FutureProvider<void>((ref) async {
  await ref.read(apiClientProvider).loadToken();
});
