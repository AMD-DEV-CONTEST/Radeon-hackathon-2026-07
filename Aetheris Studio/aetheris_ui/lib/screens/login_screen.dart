import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/auth_provider.dart';
import '../providers/session_provider.dart';
import '../theme.dart';

/// Full-screen login gate shown before the app shell, in the style of
/// Claude.ai / ChatGPT's own login pages -- a centered card, not a form
/// buried in a settings dialog.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _passwordFocus = FocusNode();
  String? _error;
  bool _submitting = false;

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    _passwordFocus.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_submitting) return;
    setState(() {
      _submitting = true;
      _error = null;
    });
    final error = await ref
        .read(authProvider.notifier)
        .login(_usernameController.text.trim(), _passwordController.text);
    if (!mounted) return;
    setState(() {
      _submitting = false;
      _error = error;
    });
    if (error == null) {
      ref.read(isAuthenticatedProvider.notifier).state = true;
    }
  }

  @override
  Widget build(BuildContext context) {
    final authAsync = ref.watch(authProvider);

    return Scaffold(
      backgroundColor: AppColors.bg,
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 380),
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: authAsync.when(
              loading: () => const Center(child: CircularProgressIndicator(color: AppColors.accentGreen)),
              error: (e, _) => Text('Could not reach the backend: $e',
                  style: const TextStyle(color: AppColors.accentRed), textAlign: TextAlign.center),
              data: (auth) {
                if (!auth.configured) {
                  return const _NoAccountConfigured();
                }
                return Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Text(
                      'AETHERIS',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: AppColors.accentGreen,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 4,
                        fontSize: 22,
                      ),
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Sign in to continue',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: AppColors.textMuted, fontSize: 13),
                    ),
                    const SizedBox(height: 32),
                    TextField(
                      controller: _usernameController,
                      autofocus: true,
                      style: const TextStyle(color: AppColors.textPrimary),
                      decoration: const InputDecoration(labelText: 'Username'),
                      onSubmitted: (_) => _passwordFocus.requestFocus(),
                    ),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _passwordController,
                      focusNode: _passwordFocus,
                      obscureText: true,
                      style: const TextStyle(color: AppColors.textPrimary),
                      decoration: const InputDecoration(labelText: 'Password'),
                      onSubmitted: (_) => _submit(),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Text(_error!, style: const TextStyle(color: AppColors.accentRed, fontSize: 12)),
                    ],
                    const SizedBox(height: 24),
                    ElevatedButton(
                      onPressed: _submitting ? null : _submit,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.accentGreen,
                        foregroundColor: Colors.black,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                      ),
                      child: _submitting
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black),
                            )
                          : const Text('Sign in'),
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}

class _NoAccountConfigured extends StatelessWidget {
  const _NoAccountConfigured();

  @override
  Widget build(BuildContext context) {
    return const Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(Icons.lock_outline, color: AppColors.textMuted, size: 32),
        SizedBox(height: 16),
        Text(
          'No local account configured yet.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AppColors.textPrimary),
        ),
        SizedBox(height: 8),
        Text(
          'Set up the local account via the backend (core/auth.py) before signing in.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AppColors.textMuted, fontSize: 12),
        ),
      ],
    );
  }
}
