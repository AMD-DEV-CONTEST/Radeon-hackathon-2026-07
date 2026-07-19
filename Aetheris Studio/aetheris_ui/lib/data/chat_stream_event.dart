/// One parsed line from the `/v1/chat/completions/stream` SSE body.
///
/// Mirrors the shapes emitted by `core/utils/agent_loop.py::stream_agent_loop`
/// (measured directly from app.py + agent_loop.py, not guessed):
/// `{"delta": "..."}` text chunks, `{"type": "...", ...}` structured events
/// (ask_user, tool_start, tool_output, agent_step, metrics, budget_exceeded,
/// rounds_exhausted, web_sources, doc_stream_open/delta, agent_prep), and a
/// final non-JSON `[DONE]` sentinel.
class ChatStreamEvent {
  final String? delta;
  final String? type;
  final Map<String, dynamic> data;
  final bool done;

  const ChatStreamEvent._({
    this.delta,
    this.type,
    this.data = const {},
    this.done = false,
  });

  factory ChatStreamEvent.delta(String text) => ChatStreamEvent._(delta: text);

  factory ChatStreamEvent.typed(String type, Map<String, dynamic> json) =>
      ChatStreamEvent._(type: type, data: json);

  factory ChatStreamEvent.done() => const ChatStreamEvent._(done: true);

  @override
  String toString() =>
      done ? 'ChatStreamEvent.done' : (delta != null ? 'delta($delta)' : 'typed($type, $data)');
}
