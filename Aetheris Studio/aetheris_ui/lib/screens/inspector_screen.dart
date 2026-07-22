import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/audit_provider.dart';
import '../providers/chat_provider.dart';
import '../providers/files_provider.dart';
import '../providers/project_provider.dart';
import '../providers/terminal_provider.dart';
import '../providers/timetravel_provider.dart';
import '../theme.dart';

/// Which Inspector tab is showing (LOG=0, TERMINAL=1, FILES=2,
/// CHANGES=3). Lives outside InspectorScreen's own State so the title
/// bar's file-changes icon (main_screen.dart) can jump straight to the
/// CHANGES tab without needing a widget-tree reference to the
/// TabController.
final inspectorTabIndexProvider = StateProvider<int>((ref) => 0);

class InspectorScreen extends ConsumerStatefulWidget {
  const InspectorScreen({super.key});

  @override
  ConsumerState<InspectorScreen> createState() => _InspectorScreenState();
}

class _InspectorScreenState extends ConsumerState<InspectorScreen> with SingleTickerProviderStateMixin {
  late final TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 5, vsync: this, initialIndex: ref.read(inspectorTabIndexProvider));
    _tabController.addListener(() {
      if (!_tabController.indexIsChanging) {
        ref.read(inspectorTabIndexProvider.notifier).state = _tabController.index;
      }
    });
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(inspectorTabIndexProvider, (prev, next) {
      if (_tabController.index != next) _tabController.animateTo(next);
    });

    return Container(
      color: AppColors.panel,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TabBar(
            controller: _tabController,
            labelColor: AppColors.accentGreen,
            unselectedLabelColor: AppColors.textMuted,
            indicatorColor: AppColors.accentGreen,
            labelStyle: const TextStyle(fontSize: 11, letterSpacing: 1),
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            tabs: const [
              Tab(text: 'LOG'),
              Tab(text: 'TERMINAL'),
              Tab(text: 'FILES'),
              Tab(text: 'CHANGES'),
              Tab(text: 'BLACKBOX'),
            ],
          ),
          const Divider(height: 1, color: AppColors.border),
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: const [
                _LogTab(),
                _TerminalTab(),
                _FilesTab(),
                _ChangesTab(),
                _BlackboxTab(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _LogTab extends ConsumerWidget {
  const _LogTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final logs = ref.watch(chatSessionsProvider.select((s) => s.executionLogs));
    if (logs.isEmpty) {
      return const Center(
        child: Text('No activity yet.', style: TextStyle(color: AppColors.textMuted, fontSize: 12)),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.all(8),
      itemCount: logs.length,
      itemBuilder: (context, i) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: SelectableText(
          logs[i],
          style: const TextStyle(color: AppColors.textMuted, fontFamily: AppFonts.mono, fontSize: 11),
        ),
      ),
    );
  }
}

class _TerminalTab extends ConsumerStatefulWidget {
  const _TerminalTab();

  @override
  ConsumerState<_TerminalTab> createState() => _TerminalTabState();
}

class _TerminalTabState extends ConsumerState<_TerminalTab> {
  final _controller = TextEditingController();
  final _scrollController = ScrollController();

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _run() {
    final cmd = _controller.text;
    if (cmd.trim().isEmpty) return;
    _controller.clear();
    ref.read(terminalProvider.notifier).run(cmd);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 150),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(terminalProvider);
    final projectPath = ref.watch(projectPathProvider).valueOrNull ?? '';

    return Column(
      children: [
        if (projectPath.isEmpty)
          const Padding(
            padding: EdgeInsets.all(12),
            child: Text(
              'Select a project folder in the sidebar to use the terminal.',
              style: TextStyle(color: AppColors.textMuted, fontSize: 11),
            ),
          ),
        Expanded(
          child: ListView.builder(
            controller: _scrollController,
            padding: const EdgeInsets.all(8),
            itemCount: state.history.length,
            itemBuilder: (context, i) {
              final entry = state.history[i];
              return Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SelectableText(
                      '\$ ${entry.command}',
                      style: const TextStyle(
                        color: AppColors.accentGreen,
                        fontFamily: AppFonts.mono,
                        fontSize: 11,
                      ),
                    ),
                    const SizedBox(height: 2),
                    SelectableText(
                      entry.output,
                      style: TextStyle(
                        color: entry.exitCode == 0 ? AppColors.textPrimary : AppColors.accentRed,
                        fontFamily: AppFonts.mono,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              );
            },
          ),
        ),
        Padding(
          padding: const EdgeInsets.all(8),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _controller,
                  enabled: projectPath.isNotEmpty && !state.running,
                  style: const TextStyle(color: AppColors.textPrimary, fontFamily: AppFonts.mono, fontSize: 12),
                  decoration: const InputDecoration(hintText: 'command...', isDense: true),
                  onSubmitted: (_) => _run(),
                ),
              ),
              const SizedBox(width: 8),
              if (state.running)
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.accentGreen),
                )
              else
                IconButton(
                  icon: const Icon(Icons.play_arrow, size: 18, color: AppColors.accentGreen),
                  onPressed: projectPath.isEmpty ? null : _run,
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _FilesTab extends ConsumerWidget {
  const _FilesTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(filesProvider);
    final projectPath = ref.watch(projectPathProvider).valueOrNull ?? '';

    if (projectPath.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(16),
          child: Text(
            'Select a project folder in the sidebar to browse files.',
            style: TextStyle(color: AppColors.textMuted, fontSize: 11),
            textAlign: TextAlign.center,
          ),
        ),
      );
    }

    if (state.error != null) {
      return Center(
        child: Text(state.error!, style: const TextStyle(color: AppColors.accentRed, fontSize: 12)),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          child: Row(
            children: [
              if (state.path.isNotEmpty)
                IconButton(
                  icon: const Icon(Icons.arrow_upward, size: 16, color: AppColors.textMuted),
                  onPressed: () => ref.read(filesProvider.notifier).openParent(),
                  tooltip: 'Back',
                  visualDensity: VisualDensity.compact,
                ),
              Expanded(
                child: Text(
                  state.path.isEmpty ? '/' : '/${state.path}',
                  style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              IconButton(
                icon: const Icon(Icons.refresh, size: 16, color: AppColors.textMuted),
                onPressed: () => ref.read(filesProvider.notifier).open(state.path),
                tooltip: 'Refresh',
                visualDensity: VisualDensity.compact,
              ),
            ],
          ),
        ),
        const Divider(height: 1, color: AppColors.border),
        Expanded(
          child: state.entries.isEmpty
              ? const Center(
                  child: Text('Empty folder.', style: TextStyle(color: AppColors.textMuted, fontSize: 11)),
                )
              : ListView.builder(
                  itemCount: state.entries.length,
                  itemBuilder: (context, i) {
                    final entry = state.entries[i];
                    return ListTile(
                      dense: true,
                      leading: Icon(
                        entry.isDir ? Icons.folder_outlined : Icons.insert_drive_file_outlined,
                        size: 16,
                        color: entry.isDir ? AppColors.accentGreen : AppColors.textMuted,
                      ),
                      title: Text(
                        entry.name,
                        style: const TextStyle(color: AppColors.textPrimary, fontSize: 12),
                      ),
                      trailing: entry.isDir
                          ? null
                          : Text(
                              '${(entry.size / 1024).toStringAsFixed(1)} KB',
                              style: const TextStyle(color: AppColors.textMuted, fontSize: 10),
                            ),
                      onTap: entry.isDir ? () => ref.read(filesProvider.notifier).openSubfolder(entry.name) : null,
                    );
                  },
                ),
        ),
      ],
    );
  }
}

/// Live list of files the agent has actually created/modified this session
/// (post-approval only -- see ChatSessionsNotifier.respondToolConfirm),
/// most recent first.
class _ChangesTab extends ConsumerWidget {
  const _ChangesTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final changes = ref.watch(chatSessionsProvider.select((s) => s.fileChanges));
    if (changes.isEmpty) {
      return const Center(
        child: Text('No files changed yet this session.', style: TextStyle(color: AppColors.textMuted, fontSize: 12)),
      );
    }
    final reversed = changes.reversed.toList();
    return ListView.builder(
      itemCount: reversed.length,
      itemBuilder: (context, i) {
        final change = reversed[i];
        final created = change.tool == 'write_file' || change.tool == 'write_files';
        return ListTile(
          dense: true,
          leading: Icon(
            created ? Icons.note_add_outlined : Icons.edit_outlined,
            size: 16,
            color: created ? AppColors.accentGreen : AppColors.accentBlue,
          ),
          title: Text(
            change.path,
            style: const TextStyle(color: AppColors.textPrimary, fontSize: 12, fontFamily: AppFonts.mono),
          ),
          subtitle: Text(
            created ? 'Created' : 'Edited',
            style: const TextStyle(color: AppColors.textMuted, fontSize: 10),
          ),
          trailing: Text(
            _relativeTime(change.timestamp),
            style: const TextStyle(color: AppColors.textMuted, fontSize: 10),
          ),
        );
      },
    );
  }

  String _relativeTime(DateTime t) {
    final diff = DateTime.now().difference(t);
    if (diff.inSeconds < 60) return '${diff.inSeconds}s';
    if (diff.inMinutes < 60) return '${diff.inMinutes}min';
    return '${diff.inHours}h';
  }
}

/// Blackbox (Fase A): the Flight Recorder timeline for the active
/// session, modeled directly on _ChangesTab's row shape (icon by type,
/// monospace summary, relative timestamp, reverse-chronological), plus a
/// "Verify integrity" action backing UC-01 (auditing a session for a
/// client). Entries are digests/lengths only, never raw file/command
/// content (invariant I5) -- the summaries below reflect that.
class _BlackboxTab extends ConsumerWidget {
  const _BlackboxTab();

  static const _icons = <String, (IconData, Color)>{
    'turn_start': (Icons.play_circle_outline, AppColors.accentBlue),
    'first_token': (Icons.bolt, AppColors.accentGreen),
    'turn_end': (Icons.stop_circle_outlined, AppColors.textMuted),
    'tool_call': (Icons.bolt_outlined, AppColors.accentBlue),
    'tool_result': (Icons.check_circle_outline, AppColors.accentGreen),
    'confirm_request': (Icons.help_outline, AppColors.accentBlue),
    'confirm_decision': (Icons.gavel_outlined, AppColors.textPrimary),
    'egress_sample': (Icons.lock_outline, AppColors.accentGreen),
    'rollback': (Icons.undo, AppColors.accentRed),
  };

  String _summarize(Map<String, dynamic> entry) {
    final type = entry['type']?.toString() ?? '?';
    final payload = entry['payload'] as Map<String, dynamic>? ?? {};
    switch (type) {
      case 'turn_start':
        return 'Turn started (${payload['mode'] ?? 'builder'})';
      case 'first_token':
        return 'First token visible';
      case 'turn_end':
        return 'Turn ended (${payload['reason'] ?? 'completed'})';
      case 'tool_call':
        return '${payload['tool'] ?? '?'} called (${payload['content_len'] ?? 0} bytes)';
      case 'tool_result':
        final exit = payload['exit_code'];
        return '${payload['tool'] ?? '?'} result${exit != null && exit != 0 ? ' (exit $exit)' : ''}';
      case 'confirm_request':
        return 'Confirmation requested: ${payload['tool'] ?? '?'}';
      case 'confirm_decision':
        return '${payload['tool'] ?? '?'}: ${payload['decision'] ?? '?'}';
      case 'egress_sample':
        final bytes = payload['external_bytes'] ?? 0;
        return bytes == 0 ? '0 B external' : '$bytes B external -- ${payload['label'] ?? 'unlabeled'}';
      case 'rollback':
        return 'Rolled back to seq ${payload['target_seq'] ?? '?'}';
      default:
        return type;
    }
  }

  Future<void> _confirmUndo(BuildContext context, WidgetRef ref, Snapshot snapshot) async {
    final notifier = ref.read(timeTravelProvider.notifier);
    final preview = await notifier.preview(snapshot);
    final diffs = (preview['diffs'] as List? ?? []).cast<Map<String, dynamic>>();

    if (!context.mounted) return;
    // Same AlertDialog chrome as chat_screen.dart's _showToolConfirmDialog
    // (red Decline / green Approve TextButtons) -- undo is a gated write
    // like any other (invariant I4), so the visual language should match.
    final approved = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('Undo this action?'),
        content: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480, maxHeight: 420),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(snapshot.message, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12)),
                const SizedBox(height: 8),
                if (diffs.isEmpty)
                  const Text('No changes to preview.', style: TextStyle(color: AppColors.textMuted, fontSize: 12))
                else
                  for (final d in diffs)
                    Container(
                      margin: const EdgeInsets.only(bottom: 8),
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: const Color(0xFF17191C),
                        border: Border.all(color: AppColors.border),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        (d['diff'] as String?)?.isNotEmpty == true ? d['diff'] as String : '${d['path']}: no textual diff',
                        style: const TextStyle(fontFamily: AppFonts.mono, fontSize: 11),
                      ),
                    ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel', style: TextStyle(color: AppColors.accentRed)),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Undo', style: TextStyle(color: AppColors.accentGreen)),
          ),
        ],
      ),
    );

    if (approved == true) {
      await notifier.rollback(snapshot);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chatId = ref.watch(chatSessionsProvider.select((s) => s.activeChatId));
    final audit = ref.watch(auditProvider);
    final entries = audit.entries.reversed.toList();
    final snapshots = ref.watch(timeTravelProvider).snapshots.where((s) => s.isPreSnapshot).toList().reversed.toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  '${audit.entries.length} entries',
                  style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
                ),
              ),
              _VerifyBadge(state: audit),
              const SizedBox(width: 8),
              TextButton(
                onPressed: chatId == null || audit.verifying
                    ? null
                    : () => ref.read(auditProvider.notifier).verify(),
                child: const Text('Verify integrity', style: TextStyle(fontSize: 11)),
              ),
            ],
          ),
        ),
        if (snapshots.isNotEmpty) ...[
          const Divider(height: 1, color: AppColors.border),
          SizedBox(
            height: 32,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              itemCount: snapshots.length,
              separatorBuilder: (_, __) => const SizedBox(width: 6),
              itemBuilder: (context, i) {
                final snap = snapshots[i];
                return ActionChip(
                  avatar: const Icon(Icons.undo, size: 14, color: AppColors.accentRed),
                  label: Text(
                    snap.message.replaceFirst('pre: ', ''),
                    style: const TextStyle(fontSize: 10, fontFamily: AppFonts.mono),
                  ),
                  onPressed: () => _confirmUndo(context, ref, snap),
                );
              },
            ),
          ),
        ],
        const Divider(height: 1, color: AppColors.border),
        Expanded(
          child: entries.isEmpty
              ? const Center(
                  child: Text('No audit entries yet this session.',
                      style: TextStyle(color: AppColors.textMuted, fontSize: 12)),
                )
              : ListView.builder(
                  itemCount: entries.length,
                  itemBuilder: (context, i) {
                    final entry = entries[i];
                    final type = entry['type']?.toString() ?? '?';
                    final iconSpec = _icons[type] ?? (Icons.circle_outlined, AppColors.textMuted);
                    final ts = entry['ts'];
                    final time = ts is num
                        ? DateTime.fromMillisecondsSinceEpoch((ts * 1000).round())
                        : DateTime.now();
                    return ListTile(
                      dense: true,
                      leading: Icon(iconSpec.$1, size: 16, color: iconSpec.$2),
                      title: Text(
                        _summarize(entry),
                        style: const TextStyle(color: AppColors.textPrimary, fontSize: 12, fontFamily: AppFonts.mono),
                      ),
                      subtitle: Text(
                        'seq ${entry['seq']} · ${entry['actor'] ?? 'system'}',
                        style: const TextStyle(color: AppColors.textMuted, fontSize: 10),
                      ),
                      trailing: Text(
                        _relativeTime(time),
                        style: const TextStyle(color: AppColors.textMuted, fontSize: 10),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }

  String _relativeTime(DateTime t) {
    final diff = DateTime.now().difference(t);
    if (diff.inSeconds < 60) return '${diff.inSeconds}s';
    if (diff.inMinutes < 60) return '${diff.inMinutes}min';
    return '${diff.inHours}h';
  }
}

class _VerifyBadge extends StatelessWidget {
  final AuditState state;
  const _VerifyBadge({required this.state});

  @override
  Widget build(BuildContext context) {
    if (state.verifying) {
      return const SizedBox(
        width: 12,
        height: 12,
        child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.accentBlue),
      );
    }
    if (state.verified == null) {
      return const Text('not checked', style: TextStyle(color: AppColors.textMuted, fontSize: 10));
    }
    if (state.verified == true) {
      return const Text('✓ verified', style: TextStyle(color: AppColors.accentGreen, fontSize: 10));
    }
    return Tooltip(
      message: state.verifyError ?? 'chain broken',
      child: const Text('✗ tampered', style: TextStyle(color: AppColors.accentRed, fontSize: 10)),
    );
  }
}
