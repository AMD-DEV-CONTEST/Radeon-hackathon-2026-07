import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/backend_launcher.dart';

/// Overridden with the real, already-used [BackendLauncher] instance in
/// `main()` -- it has to exist and run before the ProviderContainer does
/// (it's what makes the backend reachable in the first place), so this is a
/// pass-through, not a factory.
final backendLauncherProvider = Provider<BackendLauncher>((ref) {
  throw UnimplementedError('backendLauncherProvider must be overridden in main()');
});
