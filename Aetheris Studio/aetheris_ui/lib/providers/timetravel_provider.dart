import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_provider.dart';
import 'chat_provider.dart';

/// One Time-Travel snapshot (Fase C): a git shadow-ref commit covering
/// the files one write_file/write_files/edit_file call touched.
class Snapshot {
  final String commit;
  final int ts;
  final String message;
  final int? turnId;
  final List<String> paths;

  const Snapshot({
    required this.commit,
    required this.ts,
    required this.message,
    required this.turnId,
    required this.paths,
  });

  factory Snapshot.fromJson(Map<String, dynamic> json) {
    return Snapshot(
      commit: json['commit']?.toString() ?? '',
      ts: json['ts'] as int? ?? 0,
      message: json['message']?.toString() ?? '',
      turnId: json['turn_id'] as int?,
      paths: (json['paths'] as List? ?? []).map((e) => e.toString()).toList(),
    );
  }

  bool get isPreSnapshot => message.startsWith('pre:');
  bool get isPostSnapshot => message.startsWith('post:');
}

class TimeTravelState {
  final List<Snapshot> snapshots;
  const TimeTravelState({this.snapshots = const []});

  /// The highest user-message index that produced any file snapshot. A
  /// checkpoint on message N is meaningful (there's something to undo back
  /// to before it) exactly when this is >= N.
  int get maxSnapshotTurn {
    var max = 0;
    for (final s in snapshots) {
      if (s.turnId != null && s.turnId! > max) max = s.turnId!;
    }
    return max;
  }

  /// True if restoring to "before message [turnId]" would change anything --
  /// i.e. some edit happened at that message or later.
  bool hasCheckpointFor(int turnId) => maxSnapshotTurn >= turnId;
}

class TimeTravelNotifier extends StateNotifier<TimeTravelState> {
  final Ref _ref;
  String? _chatId;

  TimeTravelNotifier(this._ref) : super(const TimeTravelState());

  void watch(String? chatId) {
    if (chatId == _chatId) return;
    _chatId = chatId;
    state = const TimeTravelState();
    if (chatId != null) refresh();
  }

  Future<void> refresh() async {
    final chatId = _chatId;
    if (chatId == null) return;
    try {
      final api = _ref.read(apiClientProvider);
      final json = await api.getSnapshots(chatId);
      final snapshots = (json['snapshots'] as List? ?? [])
          .map((e) => Snapshot.fromJson(e as Map<String, dynamic>))
          .toList();
      if (_chatId == chatId) {
        state = TimeTravelState(snapshots: snapshots);
      }
    } catch (_) {
      // Best-effort -- the panel just won't show new snapshots until the
      // next manual refresh/tab reopen.
    }
  }

  /// Read-only diff preview -- what a rollback to `snapshot` WOULD change.
  Future<Map<String, dynamic>> preview(Snapshot snapshot) async {
    final chatId = _chatId;
    if (chatId == null) return {'diffs': []};
    final api = _ref.read(apiClientProvider);
    return api.previewRollback(chatId, snapshot.commit, snapshot.paths);
  }

  /// The actual undo, after the user approves the preview dialog.
  Future<Map<String, dynamic>> rollback(Snapshot snapshot) async {
    final chatId = _chatId;
    if (chatId == null) return {'error': 'no active chat'};
    final api = _ref.read(apiClientProvider);
    final result = await api.rollback(chatId, snapshot.commit, snapshot.paths);
    await refresh();
    return result;
  }

  /// Message-anchored checkpoint (Fase C): read-only combined diff of
  /// restoring the whole project to before user message [turnId].
  Future<Map<String, dynamic>> previewCheckpoint(int turnId) async {
    final chatId = _chatId;
    if (chatId == null) return {'diffs': []};
    return _ref.read(apiClientProvider).previewCheckpoint(chatId, turnId);
  }

  /// The message-anchored undo itself, after the confirm dialog.
  Future<Map<String, dynamic>> restoreCheckpoint(int turnId) async {
    final chatId = _chatId;
    if (chatId == null) return {'error': 'no active chat'};
    final result = await _ref.read(apiClientProvider).restoreCheckpoint(chatId, turnId);
    await refresh();
    return result;
  }
}

final timeTravelProvider = StateNotifierProvider<TimeTravelNotifier, TimeTravelState>((ref) {
  final notifier = TimeTravelNotifier(ref);
  ref.listen<String?>(
    chatSessionsProvider.select((s) => s.activeChatId),
    (prev, next) => notifier.watch(next),
    fireImmediately: true,
  );
  return notifier;
});
