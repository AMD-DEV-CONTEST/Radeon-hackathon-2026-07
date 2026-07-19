/// Mirrors `chat_history.py::load_chat_history`'s dict shape:
/// {role, content, token_count, compressed}.
class ChatMessage {
  final String role;
  final String content;
  final int tokenCount;
  final bool compressed;
  // False for synthetic orchestration turns (a tool result fed back to the
  // model, or the "user declined" note after a confirm-dialog rejection) --
  // real context for the model, but not something the human ever typed, so
  // the chat UI skips rendering a bubble for it.
  final bool visible;

  const ChatMessage({
    required this.role,
    required this.content,
    this.tokenCount = 0,
    this.compressed = false,
    this.visible = true,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
        role: json['role']?.toString() ?? 'assistant',
        content: json['content']?.toString() ?? '',
        tokenCount: (json['token_count'] as num?)?.toInt() ?? 0,
        compressed: json['compressed'] == true,
      );

  Map<String, String> toApiMessage() => {'role': role, 'content': content};

  ChatMessage copyWith({String? content}) => ChatMessage(
        role: role,
        content: content ?? this.content,
        tokenCount: tokenCount,
        compressed: compressed,
        visible: visible,
      );
}

/// Mirrors `chat_history.py::list_chats`'s dict shape:
/// {chat_id, title, created_at, updated_at, message_count, summary}.
class ChatSession {
  final String id;
  final String title;
  final List<ChatMessage> messages;

  const ChatSession({required this.id, required this.title, this.messages = const []});

  factory ChatSession.fromListJson(Map<String, dynamic> json) => ChatSession(
        id: json['chat_id']?.toString() ?? '',
        title: json['title']?.toString() ?? 'Chat',
      );

  ChatSession copyWith({String? title, List<ChatMessage>? messages}) => ChatSession(
        id: id,
        title: title ?? this.title,
        messages: messages ?? this.messages,
      );
}
