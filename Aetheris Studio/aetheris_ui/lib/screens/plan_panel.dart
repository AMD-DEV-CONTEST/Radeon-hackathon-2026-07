import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/chat_provider.dart';
import '../theme.dart';

/// Floating panel showing the agent's current plan (Planner mode's
/// write_plan tool -- see agent.py's `plan_update` SSE event), anchored to
/// the left edge of the app. "Aprovar" switches to Builder mode and tells
/// the model to start implementing; "Revisar" just closes the panel so the
/// user can type feedback in the normal chat input while staying in
/// Planner mode.
class PlanPanel extends ConsumerWidget {
  const PlanPanel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final plan = ref.watch(chatSessionsProvider.select((s) => s.currentPlan));
    final visible = ref.watch(chatSessionsProvider.select((s) => s.planPanelVisible));
    if (!visible || plan == null) return const SizedBox.shrink();

    return Positioned(
      left: 0,
      top: 0,
      bottom: 0,
      width: 380,
      child: Material(
        elevation: 12,
        color: AppColors.panel,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: AppColors.border)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.description_outlined, size: 16, color: AppColors.accentGreen),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text(
                      'PLANO PROPOSTO',
                      style: TextStyle(color: AppColors.textPrimary, fontSize: 12, letterSpacing: 1, fontWeight: FontWeight.bold),
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close, size: 16, color: AppColors.textMuted),
                    onPressed: () => ref.read(chatSessionsProvider.notifier).dismissPlanForRevision(),
                    visualDensity: VisualDensity.compact,
                    tooltip: 'Fechar',
                  ),
                ],
              ),
            ),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: SelectableText(
                  plan,
                  style: const TextStyle(color: AppColors.textPrimary, fontSize: 13, height: 1.5),
                ),
              ),
            ),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: const BoxDecoration(
                border: Border(top: BorderSide(color: AppColors.border)),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => ref.read(chatSessionsProvider.notifier).dismissPlanForRevision(),
                      child: const Text('Revisar', style: TextStyle(color: AppColors.textMuted)),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: ElevatedButton(
                      style: ElevatedButton.styleFrom(backgroundColor: AppColors.accentGreen),
                      onPressed: () => ref.read(chatSessionsProvider.notifier).approvePlan(),
                      child: const Text('Aprovar', style: TextStyle(color: AppColors.bg, fontWeight: FontWeight.bold)),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
