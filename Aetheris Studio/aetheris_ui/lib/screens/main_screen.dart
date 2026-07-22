import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:window_manager/window_manager.dart';

import '../providers/browser_provider.dart';
import '../providers/cartographer_provider.dart';
import '../providers/chat_provider.dart';
import '../theme.dart';
import '../widgets/telemetry_footer.dart';
import 'browser_screen.dart';
import 'chat_screen.dart';
import 'inspector_screen.dart';
import 'sidebar_screen.dart';

class MainScreen extends ConsumerStatefulWidget {
  const MainScreen({super.key});

  @override
  ConsumerState<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends ConsumerState<MainScreen> {
  bool _inspectorVisible = true;

  @override
  Widget build(BuildContext context) {
    final browserVisible = ref.watch(browserVisibleProvider);

    return Scaffold(
      backgroundColor: AppColors.bg,
      body: Column(
        children: [
          _TitleBar(
            inspectorVisible: _inspectorVisible,
            onToggleInspector: () => setState(() => _inspectorVisible = !_inspectorVisible),
            onShowFileChanges: () => setState(() => _inspectorVisible = true),
          ),
          const Divider(height: 1, color: AppColors.border),
          Expanded(
            child: Row(
              children: [
                const SizedBox(width: 280, child: SidebarScreen()),
                const VerticalDivider(width: 1, color: AppColors.border),
                Expanded(
                  // IndexedStack, not a ternary swap: BrowserScreen's state
                  // subscribes to BrowserController's webview streams
                  // (loadingState/url/historyChanged) exactly once, guarded
                  // by its own _subscribed flag -- but that guard only
                  // protects one State instance's lifetime. A ternary here
                  // destroys BrowserScreen every time the user switches back
                  // to chat and creates a brand new State (with a fresh,
                  // unset _subscribed) the next time browserVisible flips
                  // true, which then re-listens on the SAME already-
                  // subscribed single-subscription streams (BrowserController
                  // itself is a plain Provider, never disposed) and crashes
                  // with "Bad state: Stream has already been listened to."
                  // Keeping both children permanently mounted sidesteps this
                  // by construction: BrowserScreen's State, and therefore its
                  // one-time subscription, is created exactly once.
                  child: IndexedStack(
                    index: browserVisible ? 1 : 0,
                    children: const [ChatScreen(), BrowserScreen()],
                  ),
                ),
                if (_inspectorVisible) ...[
                  const VerticalDivider(width: 1, color: AppColors.border),
                  const SizedBox(width: 320, child: InspectorScreen()),
                ],
              ],
            ),
          ),
          const Divider(height: 1, color: AppColors.border),
          const TelemetryFooter(),
        ],
      ),
    );
  }
}

class _TitleBar extends ConsumerWidget {
  final bool inspectorVisible;
  final VoidCallback onToggleInspector;
  final VoidCallback onShowFileChanges;

  const _TitleBar({
    required this.inspectorVisible,
    required this.onToggleInspector,
    required this.onShowFileChanges,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final fileChangeCount = ref.watch(chatSessionsProvider.select((s) => s.fileChanges.length));
    final browserVisible = ref.watch(browserVisibleProvider);

    return SizedBox(
      height: 40,
      child: Row(
        children: [
          Expanded(
            child: DragToMoveArea(
              child: Container(
                color: AppColors.panel,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                alignment: Alignment.centerLeft,
                child: const Text(
                  'AETHERIS',
                  style: TextStyle(
                    color: AppColors.accentGreen,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 2,
                    fontSize: 13,
                  ),
                ),
              ),
            ),
          ),
          IconButton(
            tooltip: 'Browser',
            icon: Icon(
              Icons.public,
              size: 18,
              color: browserVisible ? AppColors.accentGreen : AppColors.textMuted,
            ),
            onPressed: () => ref.read(browserVisibleProvider.notifier).state = !browserVisible,
          ),
          _FileChangesButton(count: fileChangeCount, onPressed: () {
            onShowFileChanges();
            ref.read(inspectorTabIndexProvider.notifier).state = 3;
          }),
          _CartographerBadge(onPressed: () {
            onShowFileChanges();
            ref.read(inspectorTabIndexProvider.notifier).state = 4;
          }),
          IconButton(
            tooltip: 'Inspector',
            icon: Icon(
              Icons.view_sidebar_outlined,
              size: 18,
              color: inspectorVisible ? AppColors.accentGreen : AppColors.textMuted,
            ),
            onPressed: onToggleInspector,
          ),
          _WindowButton(icon: Icons.remove, onPressed: () => windowManager.minimize()),
          _WindowButton(
            icon: Icons.crop_square,
            onPressed: () async {
              if (await windowManager.isMaximized()) {
                windowManager.unmaximize();
              } else {
                windowManager.maximize();
              }
            },
          ),
          _WindowButton(
            icon: Icons.close,
            hoverColor: AppColors.accentRed,
            onPressed: () => windowManager.close(),
          ),
        ],
      ),
    );
  }
}

class _FileChangesButton extends StatelessWidget {
  final int count;
  final VoidCallback onPressed;

  const _FileChangesButton({required this.count, required this.onPressed});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 40,
      height: 40,
      child: Stack(
        alignment: Alignment.center,
        children: [
          IconButton(
            tooltip: 'Files changed this session',
            icon: const Icon(Icons.description_outlined, size: 18, color: AppColors.textMuted),
            onPressed: onPressed,
          ),
          if (count > 0)
            Positioned(
              top: 6,
              right: 4,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                decoration: BoxDecoration(
                  color: AppColors.accentGreen,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  count > 99 ? '99+' : '$count',
                  style: const TextStyle(color: AppColors.bg, fontSize: 9, fontWeight: FontWeight.bold),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// Discreet Cartographer mapping-progress badge (Fase D) -- same
/// Stack(IconButton + Positioned badge) pattern as _FileChangesButton,
/// deliberately quiet: shows a count only while actively mapping, and
/// nothing at all once the pass finishes or if the codebase is small
/// enough that there was never anything to show.
class _CartographerBadge extends ConsumerWidget {
  final VoidCallback onPressed;
  const _CartographerBadge({required this.onPressed});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(cartographerProvider).valueOrNull ?? const CartographerState();
    return SizedBox(
      width: 40,
      height: 40,
      child: Stack(
        alignment: Alignment.center,
        children: [
          IconButton(
            tooltip: status.inProgress
                ? 'Mapping codebase: ${status.mapped}/${status.total}'
                : 'Codebase map',
            icon: Icon(Icons.map_outlined, size: 18,
                color: status.inProgress ? AppColors.accentBlue : AppColors.textMuted),
            onPressed: onPressed,
          ),
          if (status.inProgress)
            Positioned(
              top: 6,
              right: 4,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                decoration: BoxDecoration(
                  color: AppColors.accentBlue,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  '${status.mapped}/${status.total}',
                  style: const TextStyle(color: AppColors.bg, fontSize: 9, fontWeight: FontWeight.bold),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _WindowButton extends StatelessWidget {
  final IconData icon;
  final VoidCallback onPressed;
  final Color? hoverColor;

  const _WindowButton({required this.icon, required this.onPressed, this.hoverColor});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 44,
      height: 40,
      child: IconButton(
        icon: Icon(icon, size: 16, color: AppColors.textMuted),
        onPressed: onPressed,
        hoverColor: (hoverColor ?? AppColors.border).withValues(alpha: 0.3),
      ),
    );
  }
}
