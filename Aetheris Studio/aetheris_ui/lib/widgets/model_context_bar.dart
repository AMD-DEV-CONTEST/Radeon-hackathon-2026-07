import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/models/app_state_models.dart';
import '../providers/chat_provider.dart';
import '../providers/model_load_provider.dart';
import '../providers/settings_provider.dart';
import '../theme.dart';

/// The whole bottom-of-chat control row: Builder/Planner mode, model
/// picker, real context-window picker, response-length ("Intelligence")
/// picker. Previously three separate widgets with three slightly different
/// pill styles crammed into a Row that overflowed/squeezed together
/// whenever the chat panel narrowed (sidebar + inspector both open). One
/// shared pill style + a Wrap (reflows onto a second line instead of
/// overflowing) fixes both the inconsistent look and the squeeze at once.
class AgentToolbar extends ConsumerWidget {
  const AgentToolbar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settingsAsync = ref.watch(settingsProvider);
    final loadState = ref.watch(modelLoadProvider);
    final mode = ref.watch(agentModeProvider);
    final contextLength = settingsAsync.valueOrNull?.contextLength ?? 2048;
    final intelligence = ref.watch(intelligenceProvider);
    final loading = loadState.status == ModelLoadStatus.loading;

    return Wrap(
      spacing: 6,
      runSpacing: 6,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        _SegmentedToggle(
          segments: const [
            _Segment(label: 'Builder', icon: Icons.bolt, value: 'builder'),
            _Segment(label: 'Planner', icon: Icons.checklist_outlined, value: 'planner'),
          ],
          value: mode,
          onChanged: (v) => ref.read(agentModeProvider.notifier).state = v,
        ),
        _Pill(
          icon: Icons.memory,
          label: settingsAsync.valueOrNull?.defaultModel.isNotEmpty == true
              ? settingsAsync.valueOrNull!.defaultModel
              : 'Select model',
          loading: loading,
          error: loadState.status == ModelLoadStatus.error,
          onTap: () => _showModelPicker(context, ref),
        ),
        _Pill(
          icon: Icons.tune,
          label: _labelFor(contextLength, contextLengthOptions),
          loading: loading,
          onTap: () => _showPicker(
            context: context,
            title: 'Context',
            unit: 'tokens',
            leftHint: 'Faster',
            rightHint: 'More context',
            options: contextLengthOptions,
            current: contextLength,
            onSelected: (v) => ref.read(modelLoadProvider.notifier).changeContextLength(v),
          ),
        ),
        _Pill(
          icon: Icons.psychology_outlined,
          label: _labelFor(intelligence, intelligenceOptions),
          onTap: () => _showPicker(
            context: context,
            title: 'Intelligence',
            unit: 'tokens',
            leftHint: 'Faster',
            rightHint: 'Smarter',
            options: intelligenceOptions,
            current: intelligence,
            onSelected: (v) => ref.read(intelligenceProvider.notifier).state = v,
          ),
        ),
        if (loadState.status == ModelLoadStatus.error)
          Text(loadState.error ?? 'Failed to load model',
              style: const TextStyle(color: AppColors.accentRed, fontSize: 11)),
      ],
    );
  }

  // Was a fixed ['Min', 'Low', 'Medium', 'High', 'Max'] list matched to
  // exactly 5 option slots -- broke silently (fell back to a raw number)
  // once contextLengthOptions/intelligenceOptions grew past 5 entries to
  // fit real long-context use (up to 65536). A plain "16K"/"32K"/"64K"
  // token count scales to any option list length and is the convention
  // every other model picker already uses, so there's no name list to
  // keep in sync with the options anymore.
  static String _labelFor(int value, List<int> options) {
    if (value >= 1024 && value % 1024 == 0) return '${value ~/ 1024}K';
    return '$value';
  }

  Future<void> _showModelPicker(BuildContext context, WidgetRef ref) async {
    final settings = ref.read(settingsProvider).valueOrNull;
    final models = settings?.availableModels ?? const <ModelInfo>[];
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

  Future<void> _showPicker({
    required BuildContext context,
    required String title,
    required String unit,
    required String leftHint,
    required String rightHint,
    required List<int> options,
    required int current,
    required ValueChanged<int> onSelected,
  }) async {
    final selected = await showDialog<int>(
      context: context,
      barrierColor: Colors.transparent,
      builder: (context) => _AnchoredPanel(
        child: _SliderPanel(
          title: title,
          unit: unit,
          leftHint: leftHint,
          rightHint: rightHint,
          options: options,
          current: current,
        ),
      ),
    );
    if (selected != null && selected != current) {
      onSelected(selected);
    }
  }
}

class _Segment {
  final String label;
  final IconData icon;
  final String value;
  const _Segment({required this.label, required this.icon, required this.value});
}

/// One bordered group with an internal divider, instead of two independently
/// bordered pills sitting next to each other -- reads as a single control
/// (which it is: builder XOR planner) rather than two unrelated buttons.
class _SegmentedToggle extends StatelessWidget {
  final List<_Segment> segments;
  final String value;
  final ValueChanged<String> onChanged;

  const _SegmentedToggle({required this.segments, required this.value, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 28,
      decoration: BoxDecoration(
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < segments.length; i++) ...[
            if (i > 0) Container(width: 1, height: 16, color: AppColors.border),
            _SegmentButton(
              segment: segments[i],
              selected: segments[i].value == value,
              onTap: () => onChanged(segments[i].value),
              firstOrLast: i == 0 || i == segments.length - 1,
              isFirst: i == 0,
              isLast: i == segments.length - 1,
            ),
          ],
        ],
      ),
    );
  }
}

class _SegmentButton extends StatelessWidget {
  final _Segment segment;
  final bool selected;
  final VoidCallback onTap;
  final bool firstOrLast;
  final bool isFirst;
  final bool isLast;

  const _SegmentButton({
    required this.segment,
    required this.selected,
    required this.onTap,
    required this.firstOrLast,
    required this.isFirst,
    required this.isLast,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.horizontal(
        left: isFirst ? const Radius.circular(7) : Radius.zero,
        right: isLast ? const Radius.circular(7) : Radius.zero,
      ),
      child: Container(
        height: 28,
        padding: const EdgeInsets.symmetric(horizontal: 10),
        color: selected ? AppColors.accentGreen.withValues(alpha: 0.12) : Colors.transparent,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(segment.icon, size: 13, color: selected ? AppColors.accentGreen : AppColors.textMuted),
            const SizedBox(width: 5),
            Text(
              segment.label,
              style: TextStyle(
                color: selected ? AppColors.accentGreen : AppColors.textMuted,
                fontSize: 11.5,
                fontWeight: selected ? FontWeight.w600 : FontWeight.normal,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool loading;
  final bool error;

  const _Pill({
    required this.icon,
    required this.label,
    required this.onTap,
    this.loading = false,
    this.error = false,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        height: 28,
        constraints: const BoxConstraints(maxWidth: 180),
        padding: const EdgeInsets.symmetric(horizontal: 10),
        decoration: BoxDecoration(
          border: Border.all(color: error ? AppColors.accentRed : AppColors.border),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (loading)
              const SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(strokeWidth: 1.6, color: AppColors.accentGreen),
              )
            else
              Icon(icon, size: 13, color: AppColors.textMuted),
            const SizedBox(width: 6),
            Flexible(
              child: Text(
                label,
                style: const TextStyle(color: AppColors.textPrimary, fontSize: 11.5),
                overflow: TextOverflow.ellipsis,
              ),
            ),
            const SizedBox(width: 3),
            const Icon(Icons.keyboard_arrow_up, size: 13, color: AppColors.textMuted),
          ],
        ),
      ),
    );
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
  final List<ModelInfo> models;
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
          child: Text('Models',
              style: TextStyle(color: AppColors.textMuted, fontSize: 11, letterSpacing: 0.5)),
        ),
        for (var i = 0; i < models.length; i++)
          _ModelRow(
            model: models[i],
            selected: models[i].name == current,
            shortcut: models[i].downloaded && i < 9 ? '${i + 1}' : null,
            onTap: models[i].downloaded ? () => Navigator.pop(context, models[i].name) : null,
          ),
      ],
    );
  }
}

class _ModelRow extends StatelessWidget {
  final ModelInfo model;
  final bool selected;
  final String? shortcut;
  final VoidCallback? onTap;

  const _ModelRow({required this.model, required this.selected, this.shortcut, required this.onTap});

  @override
  Widget build(BuildContext context) {
    // Not downloaded: shown (so the user knows it exists and how to get it)
    // but not selectable -- picking an undownloaded model used to fail
    // confusingly at load time (vte-server's own FileNotFoundError) instead
    // of being caught here, in the one place that already knows every
    // registered model's name.
    final disabled = !model.downloaded;
    final textColor = disabled
        ? AppColors.textMuted.withValues(alpha: 0.5)
        : (selected ? AppColors.textWhite : AppColors.textPrimary);
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
                model.name,
                style: TextStyle(color: textColor, fontSize: 13),
                overflow: TextOverflow.ellipsis,
              ),
            ),
            if (disabled)
              const Padding(
                padding: EdgeInsets.only(left: 6),
                child: Text('not downloaded',
                    style: TextStyle(color: AppColors.textMuted, fontSize: 10.5, fontStyle: FontStyle.italic)),
              )
            else if (shortcut != null)
              Text(shortcut!, style: const TextStyle(color: AppColors.textMuted, fontSize: 12)),
          ],
        ),
      ),
    );
  }
}

/// Shared slider panel for both the context-length and intelligence
/// pickers -- same "effort"-style slider, different title/hints/options.
class _SliderPanel extends StatefulWidget {
  final String title;
  final String unit;
  final String leftHint;
  final String rightHint;
  final List<int> options;
  final int current;

  const _SliderPanel({
    required this.title,
    required this.unit,
    required this.leftHint,
    required this.rightHint,
    required this.options,
    required this.current,
  });

  @override
  State<_SliderPanel> createState() => _SliderPanelState();
}

class _SliderPanelState extends State<_SliderPanel> {
  late double _value;

  @override
  void initState() {
    super.initState();
    final idx = widget.options.indexOf(widget.current);
    _value = (idx >= 0 ? idx : widget.options.length ~/ 2).toDouble();
  }

  @override
  Widget build(BuildContext context) {
    final size = widget.options[_value.round()];
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 6, 14, 0),
          child: Row(
            children: [
              Text(widget.title, style: const TextStyle(color: AppColors.textMuted, fontSize: 11)),
              const Spacer(),
              Text('$size ${widget.unit}',
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
            max: (widget.options.length - 1).toDouble(),
            divisions: widget.options.length - 1,
            onChanged: (v) => setState(() => _value = v),
            onChangeEnd: (v) => Navigator.pop(context, widget.options[v.round()]),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(widget.leftHint, style: const TextStyle(color: AppColors.textMuted, fontSize: 10)),
              Text(widget.rightHint, style: const TextStyle(color: AppColors.textMuted, fontSize: 10)),
            ],
          ),
        ),
      ],
    );
  }
}
