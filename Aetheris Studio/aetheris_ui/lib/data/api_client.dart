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
  // The one in-flight streamChatCompletion connection, if any -- kept on a
  // DEDICATED client (never the shared _client above, which every other
  // call here reuses) specifically so cancelActiveStream() can force-close
  // just this one request without killing the rest of the app's
  // connectivity. Breaking out of the consumer's `await for` loop alone
  // does not do this: it stops the Dart side from reading further bytes,
  // but the underlying HTTP connection stays open and the server (which
  // only notices a disconnect, never a "the reader gave up") keeps
  // generating into a socket nobody's listening to anymore.
  http.Client? _activeStreamClient;

  ApiClient({this.baseUrl = 'http://127.0.0.1:8001', http.Client? client})
      : _client = client ?? _directClient();

  /// Force-closes the current streamChatCompletion connection, if any, so
  /// the server's own request.is_disconnected() polling (see
  /// vte/server/http_server.py's sse_stream) actually notices within its
  /// ~1s check interval and stops generating -- see the field doc above
  /// for why closing the shared _client here would be wrong.
  void cancelActiveStream() {
    _activeStreamClient?.close();
    _activeStreamClient = null;
  }

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

  Future<Map<String, dynamic>> saveSettings(String defaultModel, {int? contextLength}) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/settings'),
      headers: _headers,
      body: jsonEncode({
        'default_model': defaultModel,
        if (contextLength != null) 'context_length': contextLength,
      }),
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

  /// Blackbox Egress Monitor (Fase B): the live "0 B external" indicator.
  Future<Map<String, dynamic>> egressStatus() async {
    final res = await _client.get(Uri.parse('$baseUrl/api/egress/status'), headers: _headers);
    return _decode(res);
  }

  /// Cartographer (Fase D): background codebase-mapping progress, for the
  /// discreet title-bar badge.
  Future<Map<String, dynamic>> cartographerStatus() async {
    final res = await _client.get(Uri.parse('$baseUrl/api/cartographer/status'), headers: _headers);
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
    // Blackbox (Fase A): scopes the backend's Flight Recorder audit trail
    // to this conversation -- see app.py's ChatCompletionRequest.chat_id.
    String? chatId,
  }) async* {
    final request = http.Request('POST', Uri.parse('$baseUrl/v1/chat/completions/stream'))
      ..headers.addAll(_headers)
      ..body = jsonEncode({
        'model': model,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': maxTokens,
        'mode': mode,
        if (chatId != null) 'chat_id': chatId,
      });

    final streamClient = _directClient();
    _activeStreamClient = streamClient;
    try {
      final streamedResponse = await streamClient.send(request);
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
        } else if (json.containsKey('error')) {
          // agent.py's exception branch (`event: error`, e.g. a
          // HIPSafetyError when a resolved @file reference pushes the
          // prompt past context_length) has this shape, not {type: ...} --
          // fell through both branches above and got silently dropped
          // before this, so a real generation failure just looked like the
          // agent never responding at all, with nothing in the UI
          // explaining why.
          yield ChatStreamEvent.typed('error', json);
        }
      }
    } finally {
      if (identical(_activeStreamClient, streamClient)) {
        _activeStreamClient = null;
      }
      streamClient.close();
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
  /// ChatSessionsNotifier.respondToolConfirm). `chatId` scopes the
  /// approval to the Flight Recorder audit trail (Fase A) -- optional so
  /// this still works for any call site that hasn't been updated.
  Future<Map<String, dynamic>> executeTool(String tool, String content, {String? chatId}) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/tools/execute'),
      headers: _headers,
      body: jsonEncode({'tool': tool, 'content': content, if (chatId != null) 'chat_id': chatId}),
    );
    return _decode(res);
  }

  /// The other half of the confirm gate: records a decline (no execution).
  /// Before this endpoint existed, declining was 100% client-local and
  /// invisible to the audit trail / approval-rate UX metric (Fase E).
  Future<Map<String, dynamic>> declineTool(String tool, {String content = '', String? chatId}) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/tools/decline'),
      headers: _headers,
      body: jsonEncode({'tool': tool, 'content': content, if (chatId != null) 'chat_id': chatId}),
    );
    return _decode(res);
  }

  /// Polling read of a session's Flight Recorder log (Fase A) -- backs the
  /// Blackbox Inspector tab. Live entries also arrive as `audit_entry` SSE
  /// events during an active turn; this is the source of truth for
  /// anything outside one (reopening the panel, catching up after reload).
  Future<Map<String, dynamic>> getAuditLog(String chatId, {int sinceSeq = 0}) async {
    final uri = Uri.parse('$baseUrl/api/audit/$chatId').replace(
      queryParameters: {'since_seq': sinceSeq.toString()},
    );
    final res = await _client.get(uri, headers: _headers);
    return _decode(res);
  }

  /// Reprocesses the session's hash chain server-side -- backs the
  /// Blackbox panel's "Verify integrity" button (UC-01).
  Future<Map<String, dynamic>> verifyAuditLog(String chatId) async {
    final res = await _client.get(Uri.parse('$baseUrl/api/audit/$chatId/verify'), headers: _headers);
    return _decode(res);
  }

  /// Time-Travel (Fase C): the session's shadow-ref snapshots, most recent
  /// last -- the Blackbox timeline's undo data source.
  Future<Map<String, dynamic>> getSnapshots(String chatId) async {
    final res = await _client.get(Uri.parse('$baseUrl/api/timetravel/$chatId/snapshots'), headers: _headers);
    return _decode(res);
  }

  /// Read-only diff preview for a would-be rollback -- powers the confirm
  /// dialog's content before the user actually approves an undo.
  Future<Map<String, dynamic>> previewRollback(String chatId, String targetCommit, List<String> paths) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/timetravel/preview'),
      headers: _headers,
      body: jsonEncode({'session_id': chatId, 'target_commit': targetCommit, 'paths': paths}),
    );
    return _decode(res);
  }

  /// The actual undo, after the user approves the preview dialog.
  Future<Map<String, dynamic>> rollback(String chatId, String targetCommit, List<String> paths) async {
    final res = await _client.post(
      Uri.parse('$baseUrl/api/timetravel/rollback'),
      headers: _headers,
      body: jsonEncode({'session_id': chatId, 'target_commit': targetCommit, 'paths': paths}),
    );
    return _decode(res);
  }

  void dispose() => _client.close();
}
