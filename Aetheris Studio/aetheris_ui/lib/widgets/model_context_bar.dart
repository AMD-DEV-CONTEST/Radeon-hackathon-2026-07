import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/model_load_provider.dart';
import '../providers/settings_provider.dart';
import '../theme.dart';

/// Toolbar under the chat input: model switcher + context (max output
/// tokens) switcher. Popups styled after the Claude Code model/effort
/// dropdowns the user referenced -- a dark rounded panel, a header, rows
/// with a check on the selected item and a shortcut number, and an
/// "effort"-style slider for context size.
class ModelContextBar extends ConsumerWidget {
  const ModelContextBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settingsAsync = ref.watch(settingsProvider);
    final loadState = ref.watch(modelLoadProvider);
    final contextSize = ref.watch(contextSizeProvider);

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: Row(
        children: [
          _PillButton(
            icon: loadState.status == ModelLoadStatus.loading ? null : Icons.memory,
            label: settingsAsync.valueOrNull?.defaultModel.isNotEmpty == true
                ? settingsAsync.valueOrNull!.defaultModel
                : 'Selecionar modelo',
            loading: loadState.status == ModelLoadStatus.loading,
            error: loadState.status == ModelLoadStatus.error,
            onTap: () => _showModelPicker(context, ref),
          ),
          const SizedBox(width: 8),
          _PillButton(
            icon: Icons.tune,
            label: _contextLabel(contextSize),
            onTap: () => _showContextPicker(context, ref),
          ),
          if (loadState.status == ModelLoadStatus.error) ...[
            const SizedBox(width: 8),
            Expanded(
              child: Text(loadState.error ?? 'Falha ao carregar modelo',
                  style: const TextStyle(color: AppColors.accentRed, fontSize: 11),
                  overflow: TextOverflow.ellipsis),
            ),
          ],
        ],
      ),
    );
  }

  static String _contextLabel(int size) {
    final idx = contextSizeOptions.indexOf(size);
    const names = ['Mínimo', 'Baixo', 'Médio', 'Alto', 'Máximo'];
    final name = (idx >= 0 && idx < names.length) ? names[idx] : '$size';
    return 'Contexto $name';
  }

  Future<void> _showModelPicker(BuildContext context, WidgetRef ref) async {
    final settings = ref.read(settingsProvider).valueOrNull;
    final models = settings?.availableModels ?? const <String>[];
    final current = settings?.defaultModel ?? '';

    final selected = await showDialog<String>(
      context: context,
      barrierColor: Colors.transparent,
      builder: (context) => _AnchoredPanel(
        child: _ModelPanel(models: models, current: current),
      ),
    );
    if (selected != null && selected != current) {
      await ref.read(modelLoadProvider.notifier).selectModel(selected);
    }
  }

  Future<void> _showContextPicker(BuildContext context, WidgetRef ref) async {
    final current = ref.read(contextSizeProvider);
    final selected = await showDialog<int>(
      context: context,
      barrierColor: Colors.transparent,
      builder: (context) => _AnchoredPanel(
        child: _ContextPanel(current: current),
      ),
    );
    if (selected != null) {
      ref.read(contextSizeProvider.notifier).state = selected;
    }
  }
}

/// Positions a small panel just above the bottom-left, over the chat input
/// area, with the dark rounded card look from the reference screenshots.
class _AnchoredPanel extends StatelessWidget {
  final Widget child;
  const _AnchoredPanel({required this.child});

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Positioned(
          left: 24,
          bottom: 80,
          child: Material(
            color: Colors.transparent,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 300, minWidth: 240),
              child: Container(
                decoration: BoxDecoration(
                  color: const Color(0xFF17191C),
                  border: Border.all(color: AppColors.border),
                  borderRadius: BorderRadius.circular(10),
                  boxShadow: const [
                    BoxShadow(color: Colors.black54, blurRadius: 16, offset: Offset(0, 4)),
                  ],
                ),
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: child,
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _ModelPanel extends StatelessWidget {
  final List<String> models;
  final String current;
  const _ModelPanel({required this.models, required this.current});

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(14, 6, 14, 8),
          child: Text('Modelos',
              style: TextStyle(color: AppColors.textMuted, fontSize: 11, letterSpacing: 0.5)),
        ),
        for (var i = 0; i < models.length; i++)
          _ModelRow(
            name: models[i],
            selected: models[i] == current,
            shortcut: i < 9 ? '${i + 1}' : null,
            onTap: () => Navigator.pop(context, models[i]),
          ),
      ],
    );
  }
}

class _ModelRow extends StatelessWidget {
  final String name;
  final bool selected;
  final String? shortcut;
  final VoidCallback onTap;

  const _ModelRow({required this.name, required this.selected, this.shortcut, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
        child: Row(
          children: [
            SizedBox(
              width: 18,
              child: selected
                  ? const Icon(Icons.check, size: 15, color: AppColors.accentGreen)
                  : null,
            ),
            Expanded(
              child: Text(
                name,
                style: TextStyle(
                  color: selected ? AppColors.textWhite : AppColors.textPrimary,
                  fontSize: 13,
                ),
                overflow: TextOverflow.ellipsis,
              ),
            ),
            if (shortcut != null)
              Text(shortcut!, style: const TextStyle(color: AppColors.textMuted, fontSize: 12)),
          ],
        ),
      ),
    );
  }
}

class _ContextPanel extends StatefulWidget {
  final int current;
  const _ContextPanel({required this.current});

  @override
  State<_ContextPanel> createState() => _ContextPanelState();
}

class _ContextPanelState extends State<_ContextPanel> {
  late double _value;

  @override
  void initState() {
    super.initState();
    final idx = contextSizeOptions.indexOf(widget.current);
    _value = (idx >= 0 ? idx : contextSizeOptions.length ~/ 2).toDouble();
  }

  @override
  Widget build(BuildContext context) {
    final size = contextSizeOptions[_value.round()];
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 6, 14, 0),
          child: Row(
            children: [
              const Text('Contexto', style: TextStyle(color: AppColors.textMuted, fontSize: 11)),
              const Spacer(),
              Text('$size tokens',
                  style: const TextStyle(color: AppColors.accentGreen, fontSize: 11)),
            ],
          ),
        ),
        SliderTheme(
          data: SliderTheme.of(context).copyWith(
            activeTrackColor: AppColors.accentGreen,
            inactiveTrackColor: AppColors.border,
            thumbColor: AppColors.accentGreen,
            overlayColor: AppColors.accentGreen.withValues(alpha: 0.15),
            trackHeight: 3,
          ),
          child: Slider(
            value: _value,
            min: 0,
            max: (contextSizeOptions.length - 1).toDouble(),
            divisions: contextSizeOptions.length - 1,
            onChanged: (v) => setState(() => _value = v),
            onChangeEnd: (v) => Navigator.pop(context, contextSizeOptions[v.round()]),
          ),
        ),
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('Mais rápido', style: TextStyle(color: AppColors.textMuted, fontSize: 10)),
              Text('Mais contexto', style: TextStyle(color: AppColors.textMuted, fontSize: 10)),
            ],
          ),
        ),
      ],
    );
  }
}

class _PillButton extends StatelessWidget {
  final IconData? icon;
  final String label;
  final VoidCallback onTap;
  final bool loading;
  final bool error;

  const _PillButton({
    this.icon,
    required this.label,
    required this.onTap,
    this.loading = false,
    this.error = false,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(20),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: AppColors.inputBg,
          border: Border.all(color: error ? AppColors.accentRed : AppColors.border),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (loading)
              const SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.accentGreen),
              )
            else if (icon != null)
              Icon(icon, size: 14, color: AppColors.textMuted),
            const SizedBox(width: 6),
            Text(label, style: const TextStyle(color: AppColors.textPrimary, fontSize: 12)),
            const SizedBox(width: 4),
            const Icon(Icons.keyboard_arrow_up, size: 14, color: AppColors.textMuted),
          ],
        ),
      ),
    );
  }
}
