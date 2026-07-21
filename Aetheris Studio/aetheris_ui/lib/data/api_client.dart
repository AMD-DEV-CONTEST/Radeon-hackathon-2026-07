import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

import 'chat_stream_event.dart';
import 'env_loader.dart';

/// Rules out the system/Windows proxy intercepting loopback traffic (a GUI
/// app can inherit it even when a terminal doesn't) by forcing every
/// request straight to the destination.
http.Client _directClient() {
  final ioClient = HttpClient()..findProxy = (uri) => 'DIRECT';
  return IOClient(ioClient);
}

/// Thrown for any non-2xx response. `statusCode` lets callers branch on the
/// same codes the Flet controller special-cased (401 bad credentials, 429
/// login rate limit, 400 unknown model).
class ApiException implements Exception {
  final int statusCode;
  final String message;
  ApiException(this.statusCode, this.message);

  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// Talks to the Python FastAPI backend (`app.py`) over the 12 endpoints
/// measured directly from that file -- this is the entire real HTTP contract
/// the old Flet `chat_controller.py` used, no more, no less.
class ApiClient {
  final String baseUrl;
  String? _internalToken;
  final http.Client _client;

  ApiClient({this.baseUrl = 'http://127.0.0.1:8001', http.Client? client})
      : _client = client ?? _directClient();

  /// Must be called once before any authenticated call. Reads the shared
  /// `.env` secret the backend also reads (see EnvLoader).
  Future<void> loadToken() async {
    _internalToken = await EnvLoader.loadInternalToken();
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'X-Internal-Token': ?_internalToken,
      };

  Map<String, dynamic> _decode(http.Response res) {
    if (res.statusCode < 200 || res.statusCode >= 300) {
      String detail = res.body;
      try {
        final parsed = jsonDecode(res.body);
        if (parsed is Map && parsed['detail'] != null) {
          detail = parsed['detail'].toString();
        }
      } catch (_) {}
      throw ApiException(res.statusCode, detail);
    }
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> root() async {
    final res = await _client.get(Uri.parse('$baseUrl/'));
    return _decode(res);
  }

  Future<Map<String, dynamic>> getSettings() async {
    final res = await _client.get(Uri.parse('$baseUrl/api/settings'), headers: _headers);
    return _decode(res);
  }

  Future<Map<String, dynamic>> saveSettings(String defaultModel) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/settings'),
      headers: _headers,
      body: jsonEncode({'default_model': defaultModel}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> authStatus() async {
    final res = await _client.get(Uri.parse('$baseUrl/api/auth/status'), headers: _headers);
    return _decode(res);
  }

  /// Throws [ApiException] with statusCode 401 (bad credentials) or 429
  /// (rate limited, 5 attempts/60s server-side) on failure.
  Future<Map<String, dynamic>> login(String username, String password) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/auth/login'),
      headers: _headers,
      body: jsonEncode({'username': username, 'password': password}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> listChats() async {
    final res = await _client.get(Uri.parse('$baseUrl/api/chats'), headers: _headers);
    return _decode(res);
  }

  Future<Map<String, dynamic>> createChat(String firstMessage) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/chats'),
      headers: _headers,
      body: jsonEncode({'first_message': firstMessage}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> getChatMessages(String chatId) async {
    final res =
        await _client.get(Uri.parse('$baseUrl/api/chats/$chatId/messages'), headers: _headers);
    return _decode(res);
  }

  Future<Map<String, dynamic>> appendChatMessage(String chatId, String role, String content) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/chats/$chatId/messages'),
      headers: _headers,
      body: jsonEncode({'role': role, 'content': content}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> renameChat(String chatId, String title) async {
    final res = await _client.put(
      Uri.parse('$baseUrl/api/chats/$chatId'),
      headers: _headers,
      body: jsonEncode({'title': title}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> deleteChat(String chatId) async {
    final res = await _client.delete(Uri.parse('$baseUrl/api/chats/$chatId'), headers: _headers);
    return _decode(res);
  }

  Future<Map<String, dynamic>> health() async {
    final res = await _client.get(Uri.parse('$baseUrl/api/health'), headers: _headers);
    return _decode(res);
  }

  Future<Map<String, dynamic>> telemetry() async {
    final res = await _client.get(Uri.parse('$baseUrl/api/telemetry'), headers: _headers);
    return _decode(res);
  }

  /// Blocks until the model is actually resident in VRAM (real GPU load,
  /// not just persisting a preference) -- can take several seconds.
  Future<Map<String, dynamic>> warmupModel(String model) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/vte/warmup'),
      headers: _headers,
      body: jsonEncode({'model': model}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> shutdown() async {
    final res = await _client.post(Uri.parse('$baseUrl/api/shutdown'), headers: _headers);
    return _decode(res);
  }

  /// SSE stream for `/v1/chat/completions/stream`. Parses `data: {json}`
  /// lines one at a time, yielding [ChatStreamEvent]s, ending on `[DONE]`.
  /// Mirrors the manual line-by-line parsing `chat_controller.py::send_message`
  /// did with `httpx` (no SSE client library on either side).
  Stream<ChatStreamEvent> streamChatCompletion({
    required String model,
    required List<Map<String, String>> messages,
    double temperature = 0.3,
    int maxTokens = 4096,
    String mode = 'builder',
  }) async* {
    final request = http.Request('POST', Uri.parse('$baseUrl/v1/chat/completions/stream'))
      ..headers.addAll(_headers)
      ..body = jsonEncode({
        'model': model,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': maxTokens,
        'mode': mode,
      });

    final streamedResponse = await _client.send(request);
    if (streamedResponse.statusCode < 200 || streamedResponse.statusCode >= 300) {
      final body = await streamedResponse.stream.bytesToString();
      throw ApiException(streamedResponse.statusCode, body);
    }

    final lines = streamedResponse.stream.transform(utf8.decoder).transform(const LineSplitter());
    await for (final rawLine in lines) {
      if (!rawLine.startsWith('data: ')) continue;
      final payload = rawLine.substring('data: '.length).trim();
      if (payload.isEmpty) continue;
      if (payload == '[DONE]') {
        yield ChatStreamEvent.done();
        continue;
      }
      Map<String, dynamic> json;
      try {
        json = jsonDecode(payload) as Map<String, dynamic>;
      } catch (_) {
        continue;
      }
      if (json.containsKey('delta')) {
        yield ChatStreamEvent.delta(json['delta']?.toString() ?? '');
      } else if (json.containsKey('type')) {
        yield ChatStreamEvent.typed(json['type'].toString(), json);
      }
    }
  }

  Future<Map<String, dynamic>> searchProjectFiles(String query) async {
    final uri = Uri.parse('$baseUrl/api/files/search').replace(queryParameters: {'q': query});
    final res = await _client.get(uri, headers: _headers);
    return _decode(res);
  }

  Future<Map<String, dynamic>> resolveAtReference(String path) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/files/resolve-reference'),
      headers: _headers,
      body: jsonEncode({'path': path}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> getProjectPath() async {
    final res = await _client.get(Uri.parse('$baseUrl/api/project-path'), headers: _headers);
    return _decode(res);
  }

  Future<Map<String, dynamic>> setProjectPath(String path) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/project-path'),
      headers: _headers,
      body: jsonEncode({'path': path}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> listProjectFiles({String path = ''}) async {
    final uri = Uri.parse('$baseUrl/api/files/list').replace(
      queryParameters: path.isEmpty ? null : {'path': path},
    );
    final res = await _client.get(uri, headers: _headers);
    return _decode(res);
  }

  Future<Map<String, dynamic>> runTerminalCommand(String command) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/terminal/run'),
      headers: _headers,
      body: jsonEncode({'command': command}),
    );
    return _decode(res);
  }

  /// Runs one tool from the agent's registry on demand -- used after the
  /// user approves a pending write_file/edit_file confirm dialog (see
  /// ChatSessionsNotifier.respondToolConfirm).
  Future<Map<String, dynamic>> executeTool(String tool, String content) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/tools/execute'),
      headers: _headers,
      body: jsonEncode({'tool': tool, 'content': content}),
    );
    return _decode(res);
  }

  void dispose() => _client.close();
}
