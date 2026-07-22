import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_provider.dart';
import 'chat_provider.dart';

/// Blackbox (Fase A): polls the active chat's Flight Recorder log and
/// backs the "Verify integrity" action. No persistent broadcast channel
/// exists outside an active turn (see app.py's GET /api/audit/{id}), so
/// polling is the source of truth -- audit_entry SSE events during a live
/// turn (chat_provider.dart's liveAuditEntries) just make it feel
/// immediate while one is running.
class AuditState {
  final List<Map<String, dynamic>> entries;
  final bool? verified; // null = not checked yet this session
  final String? verifyError;
  final bool verifying;

  const AuditState({this.entries = const [], this.verified, this.verifyError, this.verifying = false});

  AuditState copyWith({
    List<Map<String, dynamic>>? entries,
    Object? verified = _unset,
    Object? verifyError = _unset,
    bool? verifying,
  }) {
    return AuditState(
      entries: entries ?? this.entries,
      verified: identical(verified, _unset) ? this.verified : verified as bool?,
      verifyError: identical(verifyError, _unset) ? this.verifyError : verifyError as String?,
      verifying: verifying ?? this.verifying,
    );
  }
}

const _unset = Object();

class AuditNotifier extends StateNotifier<AuditState> {
  final Ref _ref;
  Timer? _pollTimer;
  String? _chatId;

  AuditNotifier(this._ref) : super(const AuditState());

  void watch(String? chatId) {
    if (chatId == _chatId) return;
    _chatId = chatId;
    state = const AuditState();
    _pollTimer?.cancel();
    if (chatId == null) return;
    _refresh();
    _pollTimer = Timer.periodic(const Duration(seconds: 3), (_) => _refresh());
  }

  Future<void> _refresh() async {
    final chatId = _chatId;
    if (chatId == null) return;
    try {
      final api = _ref.read(apiClientProvider);
      final json = await api.getAuditLog(chatId);
      final entries = (json['entries'] as List? ?? []).cast<Map<String, dynamic>>();
      if (_chatId == chatId) {
        state = state.copyWith(entries: entries);
      }
    } catch (_) {
      // Best-effort -- the next 3s tick just retries.
    }
  }

  Future<void> verify() async {
    final chatId = _chatId;
    if (chatId == null) return;
    state = state.copyWith(verifying: true);
    try {
      final api = _ref.read(apiClientProvider);
      final json = await api.verifyAuditLog(chatId);
      final ok = json['ok'] == true;
      final errors = (json['errors'] as List?)?.cast<String>().join('; ');
      state = state.copyWith(verified: ok, verifyError: ok ? null : (errors?.isNotEmpty == true ? errors : 'chain broken'), verifying: false);
    } catch (e) {
      state = state.copyWith(verified: false, verifyError: e.toString(), verifying: false);
    }
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }
}

final auditProvider = StateNotifierProvider<AuditNotifier, AuditState>((ref) {
  final notifier = AuditNotifier(ref);
  ref.listen<String?>(
    chatSessionsProvider.select((s) => s.activeChatId),
    (prev, next) => notifier.watch(next),
    fireImmediately: true,
  );
  return notifier;
});
