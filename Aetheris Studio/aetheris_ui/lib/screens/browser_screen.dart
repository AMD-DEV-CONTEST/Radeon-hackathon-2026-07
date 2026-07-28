import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:webview_windows/webview_windows.dart';

import '../providers/browser_provider.dart';
import '../theme.dart';

/// The embedded browser (WebView2 via webview_windows). Login is always
/// human-driven -- typed directly into the WebView2 surface, never touched
/// by Aetheris's own code. The agent's navigate_browser/read_browser_page
/// tools (see chat_provider.dart) act on the SAME controller this screen
/// renders, via browserControllerProvider, so what the agent sees is always
/// what's actually on screen.
class BrowserScreen extends ConsumerStatefulWidget {
  const BrowserScreen({super.key});

  @override
  ConsumerState<BrowserScreen> createState() => _BrowserScreenState();
}

class _BrowserScreenState extends ConsumerState<BrowserScreen> {
  final _addressController = TextEditingController();
  bool _isLoading = false;
  bool _canGoBack = false;
  bool _canGoForward = false;
  bool _subscribed = false;

  @override
  void dispose() {
    _addressController.dispose();
    super.dispose();
  }

  void _subscribeOnce(BrowserController browser) {
    if (_subscribed) return;
    _subscribed = true;
    _addressController.text = BrowserController.homeUrl;
    browser.webview.loadingState.listen((state) {
      if (mounted) setState(() => _isLoading = state == LoadingState.loading);
    });
    browser.webview.url.listen((url) {
      if (mounted) setState(() => _addressController.text = url);
    });
    browser.webview.historyChanged.listen((history) {
      if (mounted) {
        setState(() {
          _canGoBack = history.canGoBack;
          _canGoForward = history.canGoForward;
        });
      }
    });
  }

  void _navigate(BrowserController browser) {
    var url = _addressController.text.trim();
    if (url.isEmpty) return;
    if (!url.contains('://')) {
      // Bare words go to a search, anything that looks like a domain gets
      // https:// -- same heuristic every address bar uses.
      url = url.contains('.') && !url.contains(' ')
          ? 'https://$url'
          : 'https://www.google.com/search?q=${Uri.encodeQueryComponent(url)}';
    }
    browser.navigate(url);
  }

  @override
  Widget build(BuildContext context) {
    final browser = ref.watch(browserControllerProvider);

    return FutureBuilder<void>(
      future: browser.ensureInitialized(),
      builder: (context, snapshot) {
        if (browser.error != null) {
          return Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Text(
                'Could not start the embedded browser:\n${browser.error}',
                style: const TextStyle(color: AppColors.accentRed, fontSize: 12),
                textAlign: TextAlign.center,
              ),
            ),
          );
        }
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator(color: AppColors.accentGreen));
        }
        _subscribeOnce(browser);

        return Column(
          children: [
            Container(
              color: AppColors.panel,
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
              child: Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.arrow_back, size: 18, color: AppColors.textMuted),
                    onPressed: _canGoBack ? browser.webview.goBack : null,
                    visualDensity: VisualDensity.compact,
                  ),
                  IconButton(
                    icon: const Icon(Icons.arrow_forward, size: 18, color: AppColors.textMuted),
                    onPressed: _canGoForward ? browser.webview.goForward : null,
                    visualDensity: VisualDensity.compact,
                  ),
                  IconButton(
                    icon: const Icon(Icons.refresh, size: 18, color: AppColors.textMuted),
                    onPressed: browser.webview.reload,
                    visualDensity: VisualDensity.compact,
                  ),
                  const SizedBox(width: 4),
                  Expanded(
                    child: TextField(
                      controller: _addressController,
                      style: const TextStyle(color: AppColors.textPrimary, fontSize: 13),
                      decoration: const InputDecoration(
                        isDense: true,
                        hintText: 'Type a URL or search...',
                      ),
                      onSubmitted: (_) => _navigate(browser),
                    ),
                  ),
                  const SizedBox(width: 8),
                  if (_isLoading)
                    const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.accentGreen),
                    )
                  else
                    IconButton(
                      icon: const Icon(Icons.arrow_circle_right_outlined, size: 20, color: AppColors.accentGreen),
                      onPressed: () => _navigate(browser),
                      visualDensity: VisualDensity.compact,
                    ),
                ],
              ),
            ),
            const Divider(height: 1, color: AppColors.border),
            Expanded(child: Webview(browser.webview)),
          ],
        );
      },
    );
  }
}
