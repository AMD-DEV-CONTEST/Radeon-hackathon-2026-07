import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:webview_windows/webview_windows.dart';

/// Shared WebviewController for the embedded browser -- lives here instead
/// of inside BrowserScreen's own State so the agent's navigate_browser/
/// read_browser_page tools (driven from chat_provider.dart) reach the exact
/// same browser instance the user sees and logs into, not a second hidden
/// one. Login itself stays entirely human-driven (typed directly into the
/// WebView2 surface); these tools only ever navigate or read plain visible
/// text, no click/type control of page content.
class BrowserController {
  final WebviewController webview = WebviewController();
  bool isInitialized = false;
  String? error;
  Future<void>? _initFuture;

  static const homeUrl = 'https://www.google.com';
  static const _maxReadChars = 6000;

  Future<void> ensureInitialized() {
    return _initFuture ??= _init();
  }

  Future<void> _init() async {
    try {
      await webview.initialize();
      await webview.loadUrl(homeUrl);
      isInitialized = true;
    } catch (e) {
      error = e.toString();
      rethrow;
    }
  }

  Future<void> navigate(String url) async {
    await ensureInitialized();
    await webview.loadUrl(url);
  }

  /// Plain visible text of the current page (`document.body.innerText`),
  /// not a structured DOM query -- deliberately avoids CSS-selector-based
  /// element targeting, which is the OpenClaw failure mode ("Element Not
  /// Found") this design exists to sidestep. Truncated the same way every
  /// other tool result already is, to keep a busy page from blowing out
  /// the model's context.
  Future<String> readVisibleText() async {
    await ensureInitialized();
    final result = await webview.executeScript('document.body.innerText');
    var text = (result?.toString() ?? '').trim();
    if (text.isEmpty) return '(the page is empty or still loading)';
    if (text.length > _maxReadChars) {
      text = '${text.substring(0, _maxReadChars)}\n... (truncated, ${text.length} characters total)';
    }
    return text;
  }
}

final browserControllerProvider = Provider<BrowserController>((ref) => BrowserController());

/// Whether the browser panel is currently showing in the main content area
/// (vs. the chat). A navigate_browser tool call flips this to true so the
/// user can see the page load and log in if needed, rather than the agent
/// silently browsing behind a view they aren't looking at.
final browserVisibleProvider = StateProvider<bool>((ref) => false);
