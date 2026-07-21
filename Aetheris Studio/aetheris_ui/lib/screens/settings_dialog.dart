import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/auth_provider.dart';
import '../providers/session_provider.dart';
import '../theme.dart';

/// Model selection moved out of here into ModelContextBar (below the chat
/// input, Codex/Trae-style) per user feedback -- this dialog is now just
/// account/session management.
class SettingsDialog extends ConsumerWidget {
  const SettingsDialog({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authAsync = ref.watch(authProvider);

    return AlertDialog(
      backgroundColor: AppColors.panel,
      title: const Text('Settings', style: TextStyle(color: AppColors.textPrimary)),
      content: SizedBox(
        width: 380,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('LOCAL ACCOUNT', style: TextStyle(color: AppColors.textMuted, fontSize: 10)),
            const SizedBox(height: 8),
            authAsync.when(
              data: (auth) => Row(
                children: [
                  Expanded(
                    child: Text(
                      auth.isLoggedIn ? 'Signed in as: ${auth.username}' : 'Not signed in',
                      style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
                    ),
                  ),
                  if (auth.isLoggedIn)
                    TextButton(
                      onPressed: () {
                        ref.read(isAuthenticatedProvider.notifier).state = false;
                        Navigator.of(context).pop();
                      },
                      child: const Text('Sign out', style: TextStyle(color: AppColors.accentRed, fontSize: 11)),
                    ),
                ],
              ),
              loading: () => const SizedBox.shrink(),
              error: (_, _) => const SizedBox.shrink(),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
      ],
    );
  }
}
