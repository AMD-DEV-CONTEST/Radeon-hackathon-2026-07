/// Mirrors GET /api/settings: {default_model, available_models}.
class SettingsState {
  final String defaultModel;
  final List<String> availableModels;

  const SettingsState({this.defaultModel = '', this.availableModels = const []});

  factory SettingsState.fromJson(Map<String, dynamic> json) => SettingsState(
        defaultModel: json['default_model']?.toString() ?? '',
        availableModels: (json['available_models'] as List?)?.map((e) => e.toString()).toList() ??
            const [],
      );
}

/// Mirrors GET /api/auth/status: {configured, username}.
class AuthState {
  final bool configured;
  final String? username;

  const AuthState({this.configured = false, this.username});

  factory AuthState.fromJson(Map<String, dynamic> json) => AuthState(
        configured: json['configured'] == true,
        username: json['username']?.toString(),
      );

  bool get isLoggedIn => username != null;
}

/// Mirrors GET /api/health: {ollama, sqlite}. Kept as raw dynamic values
/// since `health_producer.py`'s `last_ollama`/`last_sqlite` shapes are
/// booleans/None in practice but not a fixed schema worth over-modeling.
class HealthState {
  final bool ollamaOnline;
  final bool sqliteOnline;

  const HealthState({this.ollamaOnline = false, this.sqliteOnline = false});

  factory HealthState.fromJson(Map<String, dynamic> json) => HealthState(
        ollamaOnline: json['ollama'] == true,
        sqliteOnline: json['sqlite'] == true,
      );
}
