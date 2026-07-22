import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/api_client.dart';
import '../data/models/chat_models.dart';
import '../data/models/session_file_change.dart';
import 'api_provider.dart';
import 'browser_provider.dart';
import 'model_load_provider.dart';
import 'settings_provider.dart';

class ChatSessionsState {
  final List<ChatSession> chats;
  final String? activeChatId;
  final bool loaded;
  final bool isThinking;
  final String thinkingStatus;
  final List<String> executionLogs;
  final Map<String, dynamic>? pendingAskUser;
  final Map<String, dynamic>? pendingToolConfirm;
  final List<SessionFileChange> fileChanges;
  final Map<String, dynamic>? pendingBrowserAction;
  final String? currentPlan;
  final bool planPanelVisible;
  // Which chat isThinking/pendingToolConfirm/pendingAskUser/
  // pendingBrowserAction actually belong to. A generation started for one
  // chat keeps running in the background (nothing cancels it just because
  // the user navigates away -- see sendMessage), so without this, switching
  // to a different chat mid-generation kept showing that OTHER chat's
  // "Thinking..."/cancel button and could even pop a confirm_tool dialog
  // for a tool call the currently-viewed chat never made. The UI should
  // gate all of the above on activeChatId == generatingChatId.
  final String? generatingChatId;

  const ChatSessionsState({
    this.chats = const [],
    this.activeChatId,
    this.loaded = false,
    this.isThinking = false,
    this.thinkingStatus = '',
    this.executionLogs = const [],
    this.pendingAskUser,
    this.pendingToolConfirm,
    this.fileChanges = const [],
    this.pendingBrowserAction,
    this.currentPlan,
    this.planPanelVisible = false,
    this.generatingChatId,
  });

  ChatSession? get activeChat {
    for (final c in chats) {
      if (c.id == activeChatId) return c;
    }
    return null;
  }

  ChatSessionsState copyWith({
    List<ChatSession>? chats,
    String? activeChatId,
    bool? loaded,
    bool? isThinking,
    String? thinkingStatus,
    List<String>? executionLogs,
    Object? pendingAskUser = _unset,
    Object? pendingToolConfirm = _unset,
    List<SessionFileChange>? fileChanges,
    Object? pendingBrowserAction = _unset,
    Object? currentPlan = _unset,
    bool? planPanelVisible,
    Object? generatingChatId = _unset,
  }) {
    return ChatSessionsState(
      chats: chats ?? this.chats,
      activeChatId: activeChatId ?? this.activeChatId,
      loaded: loaded ?? this.loaded,
      isThinking: isThinking ?? this.isThinking,
      thinkingStatus: thinkingStatus ?? this.thinkingStatus,
      executionLogs: executionLogs ?? this.executionLogs,
      pendingAskUser:
          identical(pendingAskUser, _unset) ? this.pendingAskUser : pendingAskUser as Map<String, dynamic>?,
      pendingToolConfirm: identical(pendingToolConfirm, _unset)
          ? this.pendingToolConfirm
          : pendingToolConfirm as Map<String, dynamic>?,
      fileChanges: fileChanges ?? this.fileChanges,
      pendingBrowserAction: identical(pendingBrowserAction, _unset)
          ? this.pendingBrowserAction
          : pendingBrowserAction as Map<String, dynamic>?,
      currentPlan: identical(currentPlan, _unset) ? this.currentPlan : currentPlan as String?,
      planPanelVisible: planPanelVisible ?? this.planPanelVisible,
      generatingChatId: identical(generatingChatId, _unset) ? this.generatingChatId : generatingChatId as String?,
    );
  }
}

const _unset = Object();

/// Builder (agent acts immediately) or Planner (agent explores read-only,
/// then proposes a plan via write_plan for review -- see agent.py::
/// BUILDER_ONLY_TOOLS/PLANNER_ONLY_TOOLS). Sent with every chat request;
/// see ChatSessionsNotifier.sendMessage.
final agentModeProvider = StateProvider<String>((ref) => 'builder');

/// The Flutter equivalent of `chat_controller.py::BackendController`'s chat
/// half -- CRUD over /api/chats/* (new endpoints, see app.py) plus the
/// streaming send flow over /v1/chat/completions/stream.
class ChatSessionsNotifier extends StateNotifier<ChatSessionsState> {
  final ApiClient _api;
  final Ref _ref;
  bool _cancelRequested = false;
  Completer<String>? _askUserCompleter;

  ChatSessionsNotifier(this._api, this._ref) : super(const ChatSessionsState());

  Future<void> init() async {
    final listJson = await _api.listChats();
    var chats = (listJson['chats'] as List)
        .map((e) => ChatSession.fromListJson(e as Map<String, dynamic>))
        .toList();
    if (chats.isEmpty) {
      final created = await _api.createChat('New Chat');
      chats = [ChatSession(id: created['chat_id'] as String, title: 'New Chat')];
    }
    final activeId = chats.first.id;
    final loaded = await _loadMessagesInto(chats, activeId);
    state = state.copyWith(chats: loaded, activeChatId: activeId, loaded: true);
  }

  Future<List<ChatSession>> _loadMessagesInto(List<ChatSession> chats, String chatId) async {
    final idx = chats.indexWhere((c) => c.id == chatId);
    if (idx == -1) return chats;
    if (chats[idx].messages.isNotEmpty) return chats;
    final json = await _api.getChatMessages(chatId);
    final messages =
        (json['messages'] as List).map((m) => ChatMessage.fromJson(m as Map<String, dynamic>)).toList();
    final updated = List<ChatSession>.from(chats);
    updated[idx] = updated[idx].copyWith(messages: messages);
    return updated;
  }

  Future<void> newChat() async {
    final created = await _api.createChat('New Chat');
    final chatId = created['chat_id'] as String;
    state = state.copyWith(
      chats: [ChatSession(id: chatId, title: 'New Chat'), ...state.chats],
      activeChatId: chatId,
    );
  }

  Future<void> renameChat(String chatId, String newTitle) async {
    await _api.renameChat(chatId, newTitle);
    state = state.copyWith(
      chats: [
        for (final c in state.chats) c.id == chatId ? c.copyWith(title: newTitle) : c,
      ],
    );
  }

  Future<void> deleteChat(String chatId) async {
    if (state.chats.length <= 1) return;
    await _api.deleteChat(chatId);
    final remaining = state.chats.where((c) => c.id != chatId).toList();
    final newActive = state.activeChatId == chatId ? remaining.first.id : state.activeChatId;
    state = state.copyWith(chats: remaining, activeChatId: newActive);
  }

  Future<void> switchChat(String chatId) async {
    final loaded = await _loadMessagesInto(state.chats, chatId);
    state = state.copyWith(chats: loaded, activeChatId: chatId);
  }

  void cancelGeneration() {
    _cancelRequested = true;
    // _cancelRequested alone only stops THIS side from reading further
    // tokens -- the underlying HTTP connection stays open and the backend
    // (which only stops on an actual disconnect, see api_client.dart's
    // cancelActiveStream doc) keeps generating regardless. Force-closing
    // the connection is what actually makes the server stop.
    _api.cancelActiveStream();
  }

  /// Resolves a pending `ask_user` dialog raised mid-stream by the agent.
  void answerAskUser(String choice) {
    _askUserCompleter?.complete(choice);
    state = state.copyWith(pendingAskUser: null);
  }

  Future<void> sendMessage(String text, {bool isHidden = false, bool visible = true}) async {
    final chatId = state.activeChatId;
    if (chatId == null || text.trim().isEmpty) return;

    _cancelRequested = false;
    var chats = List<ChatSession>.from(state.chats);
    final idx = chats.indexWhere((c) => c.id == chatId);
    if (idx == -1) return;

    final userMessage = ChatMessage(role: 'user', content: text, visible: visible);
    var messages = List<ChatMessage>.from(chats[idx].messages)..add(userMessage);
    final assistantPlaceholder = const ChatMessage(role: 'assistant', content: '');
    messages = List<ChatMessage>.from(messages)..add(assistantPlaceholder);
    chats[idx] = chats[idx].copyWith(messages: messages);
    state = state.copyWith(chats: chats, isThinking: true, thinkingStatus: 'Thinking...', generatingChatId: chatId);

    if (!isHidden) {
      await _api.appendChatMessage(chatId, 'user', text);
    }

    // settingsProvider refreshes async right after login; if the user sends
    // a message before that first fetch lands, defaultModel would read as
    // empty and the backend would silently fall back to its hardcoded
    // small default model instead of the user's real chosen one. Forcing a
    // fresh read here (cheap, only actually hits the network if the value
    // isn't in yet) guarantees the model actually sent matches Settings.
    var settings = _ref.read(settingsProvider).valueOrNull;
    if (settings == null || settings.defaultModel.isEmpty) {
      await _ref.read(settingsProvider.notifier).refresh();
      settings = _ref.read(settingsProvider).valueOrNull;
    }
    final model = settings?.defaultModel ?? '';
    final maxTokens = _ref.read(intelligenceProvider);
    final payload = messages
        .sublist(0, messages.length - 1)
        .map((m) => m.toApiMessage())
        .toList();

    // @file / @folder references (Fase 4.5, ported from the old Flet
    // AtPopup): the chat bubble keeps showing the literal "@teste.txt" the
    // user typed, but the actual API payload for THIS turn gets the real
    // file content appended -- resolved fresh each send, not persisted to
    // chat history (mirrors the old Flet controller's behavior).
    if (!isHidden && payload.isNotEmpty) {
      final augmented = await _resolveAtReferences(text);
      if (augmented != text) {
        payload[payload.length - 1] = {'role': 'user', 'content': augmented};
      }
    }

    final mode = _ref.read(agentModeProvider);
    // Accumulates the CURRENT round's raw text only, not the whole
    // multi-round stream -- cleared every time a tool call is detected
    // (see the tool_start/confirm_tool/browser_action branches below), so
    // by construction it only ever holds the text typed since the last
    // tool call: exactly the final answer once the stream ends normally.
    // Previously this held every round's raw text concatenated together,
    // so the chat bubble showed the model's literal ```tool_name fenced
    // blocks and prose preambles inline instead of just the real reply.
    final buffer = StringBuffer();
    // Live counter for 'reasoning_delta' events (see below) -- reset per
    // round the same way tool_start/tool_output already reset
    // thinkingStatus, just tracked separately since reasoning text itself
    // is never shown inline, only its progress.
    var reasoningTokenCount = 0;
    // Set only by confirm_tool/browser_action below, to agent.py's already-
    // truncated assistant_text (see that event's docstring in agent.py):
    // when the model bundles two tool calls into one response, only the
    // first ever becomes a real tool call, and persisting the model's raw,
    // unstripped text (which still shows both) makes the NEXT round's
    // history claim a second call happened that never did -- the same
    // hallucination/merge failure strip_tool_call exists to prevent
    // server-side, just bypassed if the client saves its own buffer
    // instead of this. Left null for a plain reply or an auto-executed
    // tool (list_files, read_file, bash, etc.), where the raw buffer is
    // already the right thing to save.
    String? strippedAssistantText;
    try {
      await for (final event
          in _api.streamChatCompletion(model: model, messages: payload, maxTokens: maxTokens, mode: mode)) {
        if (_cancelRequested) break;
        if (event.done) break;
        if (event.delta != null) {
          buffer.write(event.delta);
          _updateStreamingMessage(chatId, buffer.toString());
        } else if (event.type == 'error') {
          // A real generation failure (e.g. a resolved @file reference
          // pushing the prompt past context_length -- see api_client.dart's
          // error-event doc) used to be silently dropped here, leaving the
          // user staring at a response that just never arrived with no
          // indication why. Surface it the same way a normal reply would
          // show up, since the stream ends right after this either way.
          final errMsg = event.data['error']?.toString() ?? 'Unknown error';
          buffer.write('⚠️ Error generating response: $errMsg');
          _updateStreamingMessage(chatId, buffer.toString());
        } else if (event.type == 'reasoning_delta') {
          // A reasoning-capable backend's internal chain-of-thought (see
          // agent.py's stream_agent -- content from delta.reasoning,
          // never mixed into `buffer`/the visible reply). VTE's own local
          // models never emit this event at all, so this branch is a
          // no-op on the judge's real local run; it only fires against a
          // reasoning model that can otherwise burn its whole token
          // budget silently (measured: up to 122s with zero visible
          // output under the old contract). Reuses the existing
          // thinkingStatus label -- no new panel/UI needed -- so it's
          // visible within the first second or two instead of staying
          // dark for the entire reasoning phase.
          reasoningTokenCount++;
          state = state.copyWith(thinkingStatus: 'Thinking... ($reasoningTokenCount)');
        } else if (event.type == 'ask_user') {
          final completer = Completer<String>();
          _askUserCompleter = completer;
          state = state.copyWith(pendingAskUser: event.data['data'] as Map<String, dynamic>? ?? event.data);
          await completer.future;
        } else if (event.type == 'tool_start') {
          // Whatever streamed into `buffer` so far this round was a tool-
          // call preamble/fence, not a real reply -- drop it from the
          // visible bubble (it's never persisted either; only the FINAL
          // round's un-cleared buffer becomes the saved message below) and
          // show a tool-calling status instead of raw text.
          buffer.clear();
          _updateStreamingMessage(chatId, '');
          final toolName = event.data['tool']?.toString() ?? 'tool';
          state = state.copyWith(
            executionLogs: [...state.executionLogs, '[tool_start] ${jsonEncode(event.data)}'],
            thinkingStatus: 'Using $toolName...',
          );
        } else if (event.type == 'tool_output') {
          state = state.copyWith(
            executionLogs: [...state.executionLogs, '[tool_output] ${jsonEncode(event.data)}'],
            thinkingStatus: 'Thinking...',
          );
        } else if (event.type == 'confirm_tool') {
          // The backend already stopped the stream after this event (see
          // agent.py's `confirm_tool` branch) -- no need to block here, the
          // next `[DONE]` line ends this loop naturally. Approval/denial
          // happens as an entirely separate follow-up call, see
          // respondToolConfirm below. Same bubble-clearing reasoning as
          // tool_start: the confirm dialog itself (chat_screen.dart) is
          // where the user actually sees what's being proposed now.
          buffer.clear();
          _updateStreamingMessage(chatId, '');
          state = state.copyWith(pendingToolConfirm: event.data);
          strippedAssistantText = event.data['assistant_text']?.toString();
        } else if (event.type == 'browser_action') {
          // Same stateless "pause here" pattern as confirm_tool, but this
          // one auto-resolves (no human dialog) once the stream ends -- see
          // _handleBrowserAction below.
          buffer.clear();
          _updateStreamingMessage(chatId, '');
          state = state.copyWith(pendingBrowserAction: event.data);
          strippedAssistantText = event.data['assistant_text']?.toString();
        } else if (event.type == 'plan_update') {
          // Same reasoning as tool_start/confirm_tool: the plan itself
          // renders in PlanPanel, a dedicated widget with its own
          // Aprovar/Revisar buttons -- it should never ALSO show up as a
          // raw ```write_plan-fenced chat message competing with that
          // panel for attention (previously it did, which is why the
          // panel's approve/revise buttons went unnoticed in favor of
          // just typing a reply into the chat like normal).
          buffer.clear();
          _updateStreamingMessage(chatId, '');
          state = state.copyWith(
            currentPlan: event.data['plan']?.toString() ?? '',
            planPanelVisible: true,
          );
          strippedAssistantText = event.data['assistant_text']?.toString();
        }
      }
    } catch (_) {
      // Network/backend error mid-stream: keep whatever was streamed so far.
    }

    state = state.copyWith(isThinking: false, thinkingStatus: '', generatingChatId: null);
    final finalText = (strippedAssistantText != null && strippedAssistantText.isNotEmpty)
        ? strippedAssistantText
        : buffer.toString();
    if (finalText.isNotEmpty) {
      await _api.appendChatMessage(chatId, 'assistant', finalText);
    }

    if (state.pendingBrowserAction != null) {
      await _handleBrowserAction();
    }
  }

  /// Performs a navigate_browser/read_browser_page call the agent just
  /// requested (agent.py's `browser_action` event -- see
  /// core/utils/agent.py::CLIENT_EXECUTED_TOOLS) against the same
  /// BrowserController the user's browser tab renders, then feeds the
  /// result back as a hidden continuation turn. No confirmation dialog --
  /// navigating/reading isn't destructive, unlike the write_file/edit_file/
  /// risky-bash confirm flow.
  Future<void> _handleBrowserAction() async {
    final pending = state.pendingBrowserAction;
    if (pending == null) return;
    state = state.copyWith(pendingBrowserAction: null);

    final tool = pending['tool']?.toString() ?? '';
    final content = pending['content']?.toString() ?? '';
    final browser = _ref.read(browserControllerProvider);
    _ref.read(browserVisibleProvider.notifier).state = true;

    String resultText;
    try {
      if (tool == 'navigate_browser') {
        final url = content.trim();
        await browser.navigate(url);
        resultText = 'Navigated to $url';
      } else if (tool == 'read_browser_page') {
        resultText = await browser.readVisibleText();
      } else {
        resultText = 'Unknown browser tool: $tool';
      }
    } catch (e) {
      resultText = 'Error: $e';
    }

    state = state.copyWith(
      executionLogs: [...state.executionLogs, '[browser_action] ${jsonEncode({'tool': tool, 'result': resultText})}'],
    );
    // read_browser_page's result is long, unstructured page text, not a
    // file -- without an explicit nudge, smaller models (confirmed with
    // Llama 3.1 8B) sometimes fail to connect it back to the user's
    // original request and hallucinate an unrelated reply (e.g. asking for
    // a "project folder" for what was actually a Gmail inbox listing,
    // likely pattern-matching the same bracketed "[tool result]" shape
    // read_file's output uses). navigate_browser's result is just a short
    // confirmation string, unambiguous without extra framing.
    final resultMessage = tool == 'read_browser_page'
        ? '[$tool result]\n$resultText\n\nUsing the page content above, answer what I originally asked.'
        : '[$tool result]\n$resultText';
    await sendMessage(resultMessage, isHidden: true, visible: false);
  }

  /// Resolves a pending `confirm_tool` dialog (see chat_screen.dart's
  /// confirm/deny popup for write_file/edit_file). On approval, actually
  /// runs the tool via POST /api/tools/execute and feeds the result back to
  /// the model as a hidden follow-up turn, continuing the conversation
  /// exactly like the old in-loop tool_start/tool_output path did. On
  /// denial, tells the model the user stopped the run instead, so it can
  /// react (ask what to change, try something else) rather than silently
  /// stalling.
  Future<void> respondToolConfirm(bool approved) async {
    final pending = state.pendingToolConfirm;
    if (pending == null) return;
    state = state.copyWith(pendingToolConfirm: null);

    final tool = pending['tool']?.toString() ?? '';
    final content = pending['content']?.toString() ?? '';

    if (!approved) {
      await sendMessage(
        'The user stopped the run. Maybe the user will give extra information or fix something.',
        isHidden: true,
        visible: false,
      );
      return;
    }

    Map<String, dynamic> result;
    try {
      final response = await _api.executeTool(tool, content);
      result = response['result'] as Map<String, dynamic>? ?? {};
    } catch (e) {
      result = {'error': e.toString(), 'exit_code': 1};
    }
    var fileChanges = state.fileChanges;
    if (result['exit_code'] == 0 && (tool == 'write_file' || tool == 'edit_file')) {
      final path = content.split('\n').first.trim();
      if (path.isNotEmpty) {
        fileChanges = [...fileChanges, SessionFileChange(path: path, tool: tool, timestamp: DateTime.now())];
      }
    }
    state = state.copyWith(
      executionLogs: [...state.executionLogs, '[tool_output] ${jsonEncode({'tool': tool, 'result': result})}'],
      fileChanges: fileChanges,
    );
    final resultText =
        result['output']?.toString() ?? result['content']?.toString() ?? result['error']?.toString() ?? jsonEncode(result);
    await sendMessage('[$tool result]\n$resultText', isHidden: true, visible: false);
  }

  /// The user approved the current plan (plan_panel.dart's "Aprovar"
  /// button): switch back to Builder mode and tell the model to start
  /// implementing. The model then proceeds through its normal multi-round
  /// tool loop exactly like any other multi-step task.
  Future<void> approvePlan() async {
    if (state.currentPlan == null) return;
    _ref.read(agentModeProvider.notifier).state = 'builder';
    state = state.copyWith(planPanelVisible: false);
    await sendMessage(
      'The user approved the plan. Begin implementing it now.',
      isHidden: true,
      visible: false,
    );
  }

  /// The user wants to give more feedback before approving ("Revisar"):
  /// just hide the panel so the chat input is reachable again. Mode stays
  /// Planner and the plan stays in state -- the next write_plan call
  /// updates it.
  void dismissPlanForRevision() {
    state = state.copyWith(planPanelVisible: false);
  }

  static final _atReferencePattern = RegExp(r'@(\S+)');

  /// Resolves every `@path` token in `text` (file or folder under the
  /// active project) into real content via POST /api/files/resolve-reference,
  /// and returns `text` with a "[Referenced file: ...]" block appended
  /// per resolved reference. Tokens that don't resolve (a stray "@" the user
  /// typed for some other reason, e.g. an email) are silently left alone --
  /// same "best effort, never blocks sending" behavior as the old Flet
  /// AtPopup integration.
  Future<String> _resolveAtReferences(String text) async {
    final matches = _atReferencePattern.allMatches(text).toList();
    if (matches.isEmpty) return text;

    final blocks = <String>[];
    for (final match in matches) {
      final path = match.group(1)!;
      try {
        final json = await _api.resolveAtReference(path);
        final content = json['content']?.toString() ?? '';
        blocks.add('[Referenced file: $path]\n$content');
      } catch (_) {
        // Not a real project file/folder -- ignore, leave the literal text.
      }
    }
    if (blocks.isEmpty) return text;
    return '$text\n\n${blocks.join('\n\n')}';
  }

  void _updateStreamingMessage(String chatId, String content) {
    final chats = List<ChatSession>.from(state.chats);
    final idx = chats.indexWhere((c) => c.id == chatId);
    if (idx == -1) return;
    final messages = List<ChatMessage>.from(chats[idx].messages);
    if (messages.isEmpty) return;
    messages[messages.length - 1] = messages.last.copyWith(content: content);
    chats[idx] = chats[idx].copyWith(messages: messages);
    state = state.copyWith(chats: chats);
  }
}

final chatSessionsProvider = StateNotifierProvider<ChatSessionsNotifier, ChatSessionsState>((ref) {
  final notifier = ChatSessionsNotifier(ref.watch(apiClientProvider), ref);
  ref.watch(tokenReadyProvider).whenData((_) => notifier.init());
  return notifier;
});
