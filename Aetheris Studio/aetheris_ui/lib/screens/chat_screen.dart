import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/models/chat_models.dart';
import '../data/models/file_search_result.dart';
import '../providers/api_provider.dart';
import '../providers/chat_provider.dart';
import '../providers/model_load_provider.dart';
import '../theme.dart';
import '../widgets/formatted_text.dart';
import '../widgets/model_context_bar.dart';
import 'plan_panel.dart';

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _inputController = TextEditingController();
  final _scrollController = ScrollController();
  final _inputFocusNode = FocusNode();
  bool _askUserDialogOpen = false;
  bool _toolConfirmDialogOpen = false;

  // @-reference autocomplete (Fase 4.5, ported from the old Flet AtPopup).
  int _atStart = -1;
  List<FileSearchResult> _atResults = const [];
  Timer? _atDebounce;

  @override
  void initState() {
    super.initState();
    _inputController.addListener(_onInputChanged);
  }

  @override
  void dispose() {
    _inputController.removeListener(_onInputChanged);
    _inputController.dispose();
    _scrollController.dispose();
    _inputFocusNode.dispose();
    _atDebounce?.cancel();
    super.dispose();
  }

  void _onInputChanged() {
    final text = _inputController.text;
    final cursor = _inputController.selection.baseOffset;
    if (cursor < 0) {
      _closeAtPopup();
      return;
    }
    final upToCursor = text.substring(0, cursor);
    final atIndex = upToCursor.lastIndexOf('@');
    if (atIndex == -1) {
      _closeAtPopup();
      return;
    }
    final between = upToCursor.substring(atIndex + 1);
    if (between.contains(' ') || between.contains('\n')) {
      _closeAtPopup();
      return;
    }
    setState(() => _atStart = atIndex);
    _debouncedSearch(between);
  }

  void _debouncedSearch(String query) {
    _atDebounce?.cancel();
    _atDebounce = Timer(const Duration(milliseconds: 200), () async {
      try {
        final api = ref.read(apiClientProvider);
        final json = await api.searchProjectFiles(query);
        final results = (json['results'] as List)
            .map((e) => FileSearchResult.fromJson(e as Map<String, dynamic>))
            .toList();
        if (mounted && _atStart != -1) {
          setState(() => _atResults = results);
        }
      } catch (_) {
        if (mounted) setState(() => _atResults = const []);
      }
    });
  }

  void _closeAtPopup() {
    if (_atStart == -1) return;
    setState(() {
      _atStart = -1;
      _atResults = const [];
    });
  }

  void _selectAtReference(FileSearchResult result) {
    final text = _inputController.text;
    final cursor = _inputController.selection.baseOffset;
    final end = cursor < 0 ? text.length : cursor;
    final before = text.substring(0, _atStart);
    final after = text.substring(end);
    final inserted = '@${result.path} ';
    final newText = '$before$inserted$after';
    _inputController.value = TextEditingValue(
      text: newText,
      selection: TextSelection.collapsed(offset: before.length + inserted.length),
    );
    _closeAtPopup();
    _inputFocusNode.requestFocus();
  }

  void _send() {
    final text = _inputController.text.trim();
    if (text.isEmpty) return;
    _inputController.clear();
    _closeAtPopup();
    ref.read(chatSessionsProvider.notifier).sendMessage(text);
  }

  void _scrollToBottom() {
    if (!_scrollController.hasClients) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(chatSessionsProvider);
    var messages = (state.activeChat?.messages ?? const <ChatMessage>[]).where((m) => m.visible).toList();
    // The trailing assistant placeholder sits empty between tool calls now
    // (sendMessage clears it every time a tool fires, see chat_provider.dart's
    // round-buffering) -- rendering that as a bare "..." bubble right next
    // to the "Usando <tool>..." status row below is redundant clutter, not
    // useful signal. The status row alone already covers it.
    if (messages.isNotEmpty && messages.last.role == 'assistant' && messages.last.content.isEmpty) {
      messages = messages.sublist(0, messages.length - 1);
    }
    // Model warmup (auto-triggered on boot, see model_load_provider.dart)
    // used to be invisible outside the toolbar's model picker -- a user
    // typing into the input during that window got a message that just sat
    // there until VTE finished loading, with no indication why. Gate the
    // whole input row on it instead.
    final modelLoading = ref.watch(modelLoadProvider).status == ModelLoadStatus.loading;
    // A generation keeps running in the background for whichever chat
    // started it even after the user switches away (nothing cancels it on
    // navigation), so isThinking alone isn't enough to gate this -- it used
    // to show "Thinking.../Cancel" for the chat currently on screen even
    // when THAT chat has nothing in flight, because a different chat's
    // generation was still ongoing. See generatingChatId's doc in
    // chat_provider.dart.
    final isThinkingHere = state.isThinking && state.activeChatId == state.generatingChatId;

    ref.listen(chatSessionsProvider, (prev, next) {
      if (next.pendingAskUser != null && !_askUserDialogOpen) {
        _askUserDialogOpen = true;
        _showAskUserDialog(next.pendingAskUser!);
      }
      if (next.pendingToolConfirm != null && !_toolConfirmDialogOpen) {
        _toolConfirmDialogOpen = true;
        _showToolConfirmDialog(next.pendingToolConfirm!);
      }
    });

    _scrollToBottom();

    return Stack(
      children: [
        Column(
          children: [
            Expanded(
              child: messages.isEmpty
                  ? const Center(
                      child:
                          Text('Send a message to get started.', style: TextStyle(color: AppColors.textMuted)),
                    )
                  : ListView.builder(
                      controller: _scrollController,
                      padding: const EdgeInsets.all(16),
                      itemCount: messages.length,
                      itemBuilder: (context, i) => _MessageBubble(message: messages[i]),
                    ),
            ),
            if (isThinkingHere)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                child: Row(
                  children: [
                    const SizedBox(
                      width: 12,
                      height: 12,
                      child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.accentGreen),
                    ),
                    const SizedBox(width: 8),
                    Text(state.thinkingStatus, style: const TextStyle(color: AppColors.textMuted, fontSize: 12)),
                    const Spacer(),
                    TextButton(
                      onPressed: () => ref.read(chatSessionsProvider.notifier).cancelGeneration(),
                      child: const Text('Cancel', style: TextStyle(color: AppColors.accentRed, fontSize: 12)),
                    ),
                  ],
                ),
              ),
            if (modelLoading)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                child: Row(
                  children: [
                    const SizedBox(
                      width: 12,
                      height: 12,
                      child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.accentGreen),
                    ),
                    const SizedBox(width: 8),
                    const Text('Loading model on GPU...',
                        style: TextStyle(color: AppColors.textMuted, fontSize: 12)),
                  ],
                ),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _inputController,
                      focusNode: _inputFocusNode,
                      enabled: !modelLoading,
                      style: const TextStyle(color: AppColors.textPrimary),
                      decoration: InputDecoration(
                        hintText: modelLoading
                            ? 'Waiting for the model to load...'
                            : 'Ask something... use @ to reference a file',
                      ),
                      onSubmitted: (_) => _send(),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    icon: const Icon(Icons.send, color: AppColors.accentGreen),
                    onPressed: modelLoading ? null : _send,
                  ),
                ],
              ),
            ),
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 8, 16, 12),
              child: AgentToolbar(),
            ),
          ],
        ),
        const PlanPanel(),
        if (_atStart != -1 && _atResults.isNotEmpty)
          Positioned(
            left: 24,
            right: 24,
            bottom: 90,
            child: _AtReferencePopup(results: _atResults, onSelect: _selectAtReference),
          ),
      ],
    );
  }

  Future<void> _showAskUserDialog(Map<String, dynamic> payload) async {
    final question = payload['question']?.toString() ?? payload['prompt']?.toString() ?? 'The agent needs a decision.';
    final options = (payload['options'] as List?)?.map((e) => e.toString()).toList() ?? const <String>[];

    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('Agent confirmation'),
        content: Text(question),
        actions: options.isEmpty
            ? [
                TextButton(
                  onPressed: () {
                    ref.read(chatSessionsProvider.notifier).answerAskUser('ok');
                    Navigator.pop(context);
                  },
                  child: const Text('OK'),
                ),
              ]
            : [
                for (final opt in options)
                  TextButton(
                    onPressed: () {
                      ref.read(chatSessionsProvider.notifier).answerAskUser(opt);
                      Navigator.pop(context);
                    },
                    child: Text(opt),
                  ),
              ],
      ),
    );
    _askUserDialogOpen = false;
  }

  /// Confirm/deny popup for a pending write_file/edit_file/risky-bash call
  /// (agent.py's `confirm_tool` event -- see core/utils/agent.py::
  /// _needs_confirmation). Approving actually runs the tool and feeds the
  /// result back to the model; denying tells the model the user stopped the
  /// run instead.
  /// Splits write_files' `<<<FILE: path>>>\n<content>` blocks (see
  /// core/utils/tools.py::_run_write_files) into (path, content) pairs for
  /// the compact per-file dialog below. Mirrors that function's own
  /// splitting, not shared code, since this is Dart and that's Python.
  static List<(String, String)> _splitWriteFiles(String content) {
    final marker = RegExp(r'<<<FILE:\s*(.+?)\s*>>>\n');
    final matches = marker.allMatches(content).toList();
    final result = <(String, String)>[];
    for (var i = 0; i < matches.length; i++) {
      final path = matches[i].group(1)!.trim();
      final bodyStart = matches[i].end;
      final bodyEnd = i + 1 < matches.length ? matches[i + 1].start : content.length;
      var body = content.substring(bodyStart, bodyEnd);
      if (body.endsWith('\n')) body = body.substring(0, body.length - 1);
      result.add((path, body));
    }
    return result;
  }

  Future<void> _showToolConfirmDialog(Map<String, dynamic> payload) async {
    final tool = payload['tool']?.toString() ?? 'tool';
    final content = payload['content']?.toString() ?? '';
    final firstLine = content.split('\n').first.trim();
    String title;
    String previewLabel;
    if (tool == 'edit_file') {
      title = 'The agent wants to edit a file';
      previewLabel = firstLine;
    } else if (tool == 'bash') {
      title = 'The agent wants to run a potentially dangerous command';
      previewLabel = 'Command:';
    } else if (tool == 'write_files') {
      title = 'The agent wants to create/overwrite ${_splitWriteFiles(content).length} files';
      previewLabel = '';
    } else {
      title = 'The agent wants to create/overwrite a file';
      previewLabel = firstLine;
    }

    // write_files gets its own compact, per-file collapsed list (see
    // _splitWriteFiles) instead of one long content dump -- dumping every
    // file's full text at once was the actual reported complaint (cuts off
    // the screen with more than one file). Everything else keeps the
    // single scrollable-content dialog, capped a bit tighter than before.
    final dialogBody = tool == 'write_files'
        ? _WriteFilesSummary(files: _splitWriteFiles(content))
        : Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (previewLabel.isNotEmpty) ...[
                Text(previewLabel, style: const TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
              ],
              Container(
                constraints: const BoxConstraints(maxHeight: 220),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFF17191C),
                  border: Border.all(color: AppColors.border),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: SingleChildScrollView(
                  child: Text(content, style: const TextStyle(fontFamily: AppFonts.mono, fontSize: 12)),
                ),
              ),
            ],
          );

    final approved = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480, maxHeight: 420),
          child: dialogBody,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Decline', style: TextStyle(color: AppColors.accentRed)),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Approve', style: TextStyle(color: AppColors.accentGreen)),
          ),
        ],
      ),
    );

    _toolConfirmDialogOpen = false;
    ref.read(chatSessionsProvider.notifier).respondToolConfirm(approved ?? false);
  }
}

/// Compact per-file list for a write_files confirm dialog: each file is one
/// collapsed row (path + size), expandable on tap for the full content --
/// approving/declining doesn't require scrolling through every file's text
/// first, but it's still one tap away for anyone who wants to check.
class _WriteFilesSummary extends StatefulWidget {
  final List<(String, String)> files;
  const _WriteFilesSummary({required this.files});

  @override
  State<_WriteFilesSummary> createState() => _WriteFilesSummaryState();
}

class _WriteFilesSummaryState extends State<_WriteFilesSummary> {
  final Set<int> _expanded = {};

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < widget.files.length; i++) ...[
            if (i > 0) const SizedBox(height: 6),
            _WriteFileRow(
              path: widget.files[i].$1,
              content: widget.files[i].$2,
              expanded: _expanded.contains(i),
              onToggle: () => setState(() {
                if (!_expanded.add(i)) _expanded.remove(i);
              }),
            ),
          ],
        ],
      ),
    );
  }
}

class _WriteFileRow extends StatelessWidget {
  final String path;
  final String content;
  final bool expanded;
  final VoidCallback onToggle;

  const _WriteFileRow({required this.path, required this.content, required this.expanded, required this.onToggle});

  @override
  Widget build(BuildContext context) {
    final lineCount = content.isEmpty ? 0 : content.split('\n').length;
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF17191C),
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InkWell(
            onTap: onToggle,
            borderRadius: BorderRadius.circular(6),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              child: Row(
                children: [
                  Icon(expanded ? Icons.expand_less : Icons.expand_more, size: 16, color: AppColors.textMuted),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(path,
                        style: const TextStyle(fontFamily: AppFonts.mono, fontSize: 12, fontWeight: FontWeight.bold),
                        overflow: TextOverflow.ellipsis),
                  ),
                  Text('$lineCount lines · ${content.length} bytes',
                      style: const TextStyle(color: AppColors.textMuted, fontSize: 11)),
                ],
              ),
            ),
          ),
          if (expanded)
            Container(
              constraints: const BoxConstraints(maxHeight: 200),
              padding: const EdgeInsets.fromLTRB(10, 0, 10, 10),
              child: SingleChildScrollView(
                child: Text(content, style: const TextStyle(fontFamily: AppFonts.mono, fontSize: 12)),
              ),
            ),
        ],
      ),
    );
  }
}

class _AtReferencePopup extends StatelessWidget {
  final List<FileSearchResult> results;
  final ValueChanged<FileSearchResult> onSelect;

  const _AtReferencePopup({required this.results, required this.onSelect});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: Container(
        constraints: const BoxConstraints(maxHeight: 240),
        decoration: BoxDecoration(
          color: const Color(0xFF17191C),
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(10),
          boxShadow: const [BoxShadow(color: Colors.black54, blurRadius: 16, offset: Offset(0, 4))],
        ),
        child: ListView.builder(
          shrinkWrap: true,
          padding: const EdgeInsets.symmetric(vertical: 4),
          itemCount: results.length,
          itemBuilder: (context, i) {
            final r = results[i];
            return InkWell(
              onTap: () => onSelect(r),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                child: Row(
                  children: [
                    Icon(
                      r.isDir ? Icons.folder_outlined : Icons.insert_drive_file_outlined,
                      size: 14,
                      color: r.isDir ? AppColors.accentGreen : AppColors.textMuted,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        r.path,
                        style: const TextStyle(color: AppColors.textPrimary, fontSize: 12),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  final ChatMessage message;

  const _MessageBubble({required this.message});

  @override
  Widget build(BuildContext context) {
    final isUser = message.role == 'user';
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: const BoxConstraints(maxWidth: 640),
        decoration: BoxDecoration(
          color: isUser ? AppColors.accentGreen.withValues(alpha: 0.12) : AppColors.panel,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(8),
        ),
        child: FormattedText(
          text: message.content.isEmpty ? '...' : message.content,
          proseColor: AppColors.textPrimary,
        ),
      ),
    );
  }
}
