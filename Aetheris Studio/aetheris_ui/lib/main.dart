import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:window_manager/window_manager.dart';

import 'data/env_loader.dart';
import 'providers/api_provider.dart';
import 'providers/backend_launcher_provider.dart';
import 'providers/model_load_provider.dart';
import 'providers/session_provider.dart';
import 'screens/login_screen.dart';
import 'screens/main_screen.dart';
import 'services/backend_launcher.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();

  const windowOptions = WindowOptions(
    size: Size(1200, 800),
    minimumSize: Size(1000, 700),
    center: true,
    backgroundColor: AppColors.bg,
    titleBarStyle: TitleBarStyle.hidden,
    title: 'Aetheris Desktop',
  );
  await windowManager.waitUntilReadyToShow(windowOptions, () async {
    await windowManager.show();
    await windowManager.focus();
  });
  // setPreventClose is intentionally NOT called here. It used to be, which
  // caused a real bug: prevent-close took effect immediately, but the only
  // WindowListener that ever calls windowManager.destroy() to actually
  // finish closing lives on AetherisApp (_AetherisAppState), which only
  // mounts once the backend is confirmed reachable. If the backend never
  // comes up, _Bootstrap never gets past its loading/error screen,
  // AetherisApp never mounts, no listener is ever registered to release
  // the close -- the window hangs forever and has to be killed from Task
  // Manager. Prevent-close is now armed only once AetherisApp itself is
  // ready to handle it (see its initState).

  runApp(const _Bootstrap());
}

/// Runs before the real app: makes sure app.py is reachable (starting it if
/// needed, see BackendLauncher) and the shared `.env` token is readable,
/// showing a spinner/error instead of a blank window while that happens.
class _Bootstrap extends StatefulWidget {
  const _Bootstrap();

  @override
  State<_Bootstrap> createState() => _BootstrapState();
}

class _BootstrapState extends State<_Bootstrap> {
  final _launcher = BackendLauncher();
  ProviderContainer? _container;
  String? _error;

  @override
  void initState() {
    super.initState();
    _boot();
  }

  Future<void> _boot() async {
    setState(() => _error = null);
    final alive = await _launcher.ensureRunning();
    if (!alive) {
      setState(() =>
          _error = 'Could not start or connect to the backend (app.py). Check that the project is in the expected location.');
      return;
    }
    final container = ProviderContainer(
      overrides: [backendLauncherProvider.overrideWithValue(_launcher)],
    );
    await container.read(tokenReadyProvider.future);
    setState(() => _container = container);
  }

  @override
  Widget build(BuildContext context) {
    if (_container != null) {
      return UncontrolledProviderScope(container: _container!, child: const AetherisApp());
    }
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: Scaffold(
        backgroundColor: AppColors.bg,
        body: Center(
          child: _error != null
              ? Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.cloud_off, color: AppColors.accentRed, size: 32),
                    const SizedBox(height: 16),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 32),
                      child: Text(_error!,
                          textAlign: TextAlign.center, style: const TextStyle(color: AppColors.textPrimary)),
                    ),
                    const SizedBox(height: 16),
                    ElevatedButton(onPressed: _boot, child: const Text('Try again')),
                  ],
                )
              : const Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircularProgressIndicator(color: AppColors.accentGreen),
                    SizedBox(height: 16),
                    Text('Iniciando backend...', style: TextStyle(color: AppColors.textMuted)),
                  ],
                ),
        ),
      ),
    );
  }
}

class AetherisApp extends ConsumerStatefulWidget {
  const AetherisApp({super.key});

  @override
  ConsumerState<AetherisApp> createState() => _AetherisAppState();
}

class _AetherisAppState extends ConsumerState<AetherisApp> with WindowListener {
  @override
  void initState() {
    super.initState();
    windowManager.addListener(this);
    windowManager.setPreventClose(true);
  }

  @override
  void dispose() {
    windowManager.removeListener(this);
    super.dispose();
  }

  @override
  void onWindowClose() async {
    // Always shuts the backend down on close -- see BackendLauncher.shutdown
    // for why this is unconditional now (was gated on launchedByUs, which
    // let orphaned backends accumulate across sessions).
    final token = await EnvLoader.loadInternalToken();
    if (token != null) {
      await ref.read(backendLauncherProvider).shutdown(token);
    }
    await windowManager.destroy();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Aetheris Desktop',
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: const _AppGate(),
    );
  }
}

/// Gates entry to [MainScreen] behind [LoginScreen], the way Claude.ai/
/// ChatGPT never show their app shell before authentication.
class _AppGate extends ConsumerWidget {
  const _AppGate();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // VTE doesn't need an authenticated session to start loading -- touch
    // modelLoadProvider here, at the earliest point that's guaranteed to
    // build (right after the backend is reachable, before login), so
    // warmup runs in parallel with the user typing their password instead
    // of waiting for MainScreen to mount. Riverpod providers are lazy
    // (nothing runs until first read), so this watch is what actually
    // starts the auto-warmup listener in model_load_provider.dart, not
    // just a formality.
    ref.watch(modelLoadProvider);
    final authenticated = ref.watch(isAuthenticatedProvider);
    return authenticated ? const MainScreen() : const LoginScreen();
  }
}
