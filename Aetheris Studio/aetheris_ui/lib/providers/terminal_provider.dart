import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/api_client.dart';
import 'api_provider.dart';

class TerminalEntry {
  final String command;
  final String output;
  final int exitCode;
  const TerminalEntry({required this.command, required this.output, required this.exitCode});
}

class TerminalState {
  final List<TerminalEntry> history;
  final bool running;
  const TerminalState({this.history = const [], this.running = false});
}

/// Backs the Inspector "Terminal" tab -- runs a command in the active
/// project folder via POST /api/terminal/run (see app.py; not sandboxed
/// beyond cwd confinement, same trust model as the agent's own bash tool).
class TerminalNotifier extends StateNotifier<TerminalState> {
  final ApiClient _api;
  TerminalNotifier(this._api) : super(const TerminalState());

  Future<void> run(String command) async {
    if (command.trim().isEmpty) return;
    state = TerminalState(history: state.history, running: true);
    try {
      final json = await _api.runTerminalCommand(command);
      final entry = TerminalEntry(
        command: command,
        output: json['output']?.toString() ?? '',
        exitCode: (json['exit_code'] as num?)?.toInt() ?? -1,
      );
      state = TerminalState(history: [...state.history, entry], running: false);
    } on ApiException catch (e) {
      final entry = TerminalEntry(command: command, output: e.message, exitCode: -1);
      state = TerminalState(history: [...state.history, entry], running: false);
    } catch (e) {
      final entry = TerminalEntry(command: command, output: e.toString(), exitCode: -1);
      state = TerminalState(history: [...state.history, entry], running: false);
    }
  }

  void clear() => state = const TerminalState();
}

final terminalProvider = StateNotifierProvider<TerminalNotifier, TerminalState>((ref) {
  return TerminalNotifier(ref.watch(apiClientProvider));
});
