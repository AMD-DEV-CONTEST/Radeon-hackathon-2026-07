import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/models/chat_models.dart';
import '../data/models/file_search_result.dart';
import '../providers/api_provider.dart';
import '../providers/chat_provider.dart';
import '../providers/model_load_provider.dart';
import '../theme.dart';
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
    final messages = (state.activeChat?.messages ?? const <ChatMessage>[]).where((m) => m.visible).toList();
    // Model warmup (auto-triggered on boot, see model_load_provider.dart)
    // used to be invisible outside the toolbar's model picker -- a user
    // typing into the input during that window got a message that just sat
    // there until VTE finished loading, with no indication why. Gate the
    // whole input row on it instead.
    final modelLoading = ref.watch(modelLoadProvider).status == ModelLoadStatus.loading;

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
                          Text('Envie uma mensagem para começar.', style: TextStyle(color: AppColors.textMuted)),
                    )
                  : ListView.builder(
                      controller: _scrollController,
                      padding: const EdgeInsets.all(16),
                      itemCount: messages.length,
                      itemBuilder: (context, i) => _MessageBubble(message: messages[i]),
                    ),
            ),
            if (state.isThinking)
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
                      child: const Text('Cancelar', style: TextStyle(color: AppColors.accentRed, fontSize: 12)),
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
                    const Text('Carregando modelo na GPU...',
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
                            ? 'Aguardando o modelo carregar...'
                            : 'Pergunte alguma coisa... use @ para referenciar um arquivo',
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
              padding: EdgeInsets.symmetric(horizontal: 16),
              child: _ModeToggle(),
            ),
            const Padding(
              padding: EdgeInsets.only(bottom: 12, top: 8),
              child: ModelContextBar(),
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
    final question = payload['question']?.toString() ?? payload['prompt']?.toString() ?? 'O agente precisa de uma decisão.';
    final options = (payload['options'] as List?)?.map((e) => e.toString()).toList() ?? const <String>[];

    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('Confirmação do agente'),
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
  Future<void> _showToolConfirmDialog(Map<String, dynamic> payload) async {
    final tool = payload['tool']?.toString() ?? 'ferramenta';
    final content = payload['content']?.toString() ?? '';
    final firstLine = content.split('\n').first.trim();
    String title;
    String previewLabel;
    if (tool == 'edit_file') {
      title = 'O agente quer editar um arquivo';
      previewLabel = firstLine;
    } else if (tool == 'bash') {
      title = 'O agente quer executar um comando potencialmente perigoso';
      previewLabel = 'Comando:';
    } else {
      title = 'O agente quer criar/sobrescrever um arquivo';
      previewLabel = firstLine;
    }

    final approved = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(previewLabel, style: const TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Container(
                constraints: const BoxConstraints(maxHeight: 260),
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
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Recusar', style: TextStyle(color: AppColors.accentRed)),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Aprovar', style: TextStyle(color: AppColors.accentGreen)),
          ),
        ],
      ),
    );

    _toolConfirmDialogOpen = false;
    ref.read(chatSessionsProvider.notifier).respondToolConfirm(approved ?? false);
  }
}

/// Builder/Planner switch (see agent_provider.dart's agentModeProvider and
/// core/utils/agent.py's mode-gated tool dispatch). Builder acts
/// immediately; Planner explores read-only and proposes a plan for review
/// via PlanPanel before anything actually changes.
class _ModeToggle extends ConsumerWidget {
  const _ModeToggle();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(agentModeProvider);
    return Row(
      children: [
        _ModeButton(
          label: 'Builder',
          icon: Icons.bolt,
          selected: mode == 'builder',
          onTap: () => ref.read(agentModeProvider.notifier).state = 'builder',
        ),
        const SizedBox(width: 6),
        _ModeButton(
          label: 'Planner',
          icon: Icons.checklist_outlined,
          selected: mode == 'planner',
          onTap: () => ref.read(agentModeProvider.notifier).state = 'planner',
        ),
      ],
    );
  }
}

class _ModeButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  const _ModeButton({required this.label, required this.icon, required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(6),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: selected ? AppColors.accentGreen.withValues(alpha: 0.12) : Colors.transparent,
          border: Border.all(color: selected ? AppColors.accentGreen : AppColors.border),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 13, color: selected ? AppColors.accentGreen : AppColors.textMuted),
            const SizedBox(width: 5),
            Text(
              label,
              style: TextStyle(
                color: selected ? AppColors.accentGreen : AppColors.textMuted,
                fontSize: 11,
                fontWeight: selected ? FontWeight.bold : FontWeight.normal,
              ),
            ),
          ],
        ),
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
        child: SelectableText(
          message.content.isEmpty ? '...' : message.content,
          style: TextStyle(
            color: isUser ? AppColors.textPrimary : AppColors.textPrimary,
            fontFamily: message.content.contains('```') ? AppFonts.mono : null,
            fontSize: 13,
          ),
        ),
      ),
    );
  }
}
