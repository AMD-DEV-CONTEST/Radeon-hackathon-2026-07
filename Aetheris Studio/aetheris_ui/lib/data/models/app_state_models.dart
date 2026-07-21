/// Mirrors GET /api/settings: {default_model, context_length, available_models}.
class SettingsState {
  final String defaultModel;
  final int contextLength;
  final List<String> availableModels;

  const SettingsState({this.defaultModel = '', this.contextLength = 2048, this.availableModels = const []});

  factory SettingsState.fromJson(Map<String, dynamic> json) => SettingsState(
        defaultModel: json['default_model']?.toString() ?? '',
        contextLength: (json['context_length'] as num?)?.toInt() ?? 2048,
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

/// Mirrors GET /api/telemetry, itself a proxy for vte-server's own
/// /telemetry: live hipMemGetInfo VRAM numbers and the last measured decode
/// speed, not estimates. `connected: false` (vte-server unreachable, e.g.
/// still loading, or a remote tunnel down) is a normal, displayable state,
/// not treated as an error by callers.
class TelemetryState {
  final bool connected;
  final String gpuName;
  final String gpuArch;
  final int numCus;
  final int vramTotalBytes;
  final int vramUsedBytes;
  final double decodingSpeedTps;

  const TelemetryState({
    this.connected = false,
    this.gpuName = '',
    this.gpuArch = '',
    this.numCus = 0,
    this.vramTotalBytes = 0,
    this.vramUsedBytes = 0,
    this.decodingSpeedTps = 0.0,
  });

  factory TelemetryState.fromJson(Map<String, dynamic> json) => TelemetryState(
        connected: json['connected'] == true,
        gpuName: json['gpu_name']?.toString() ?? '',
        gpuArch: json['gpu_arch']?.toString() ?? '',
        numCus: (json['num_cus'] as num?)?.toInt() ?? 0,
        vramTotalBytes: (json['vram_total_bytes'] as num?)?.toInt() ?? 0,
        vramUsedBytes: (json['vram_used_bytes'] as num?)?.toInt() ?? 0,
        decodingSpeedTps: (json['decoding_speed_tps'] as num?)?.toDouble() ?? 0.0,
      );

  /// Some GPU/driver combinations (confirmed: an AMD Radeon Cloud W7900
  /// passthrough instance) report a generic "AMD Radeon Graphics" from
  /// `hipDeviceProp_t.name` instead of the specific card model. Verified
  /// against rocminfo and amd-smi directly, both return the same generic
  /// string on that box, so this isn't something to fix by reading a
  /// different field. Falls back to the architecture (e.g. "gfx1102"),
  /// still real and specific, instead of showing an unhelpful generic name
  /// that reads as a placeholder. A real card name (e.g. a local RX 7600)
  /// is used as-is.
  String get displayGpuName {
    if (gpuName.isEmpty || gpuName == 'AMD Radeon Graphics') {
      return gpuArch.isNotEmpty ? gpuArch : gpuName;
    }
    return gpuName;
  }

  double get vramTotalGb => vramTotalBytes / (1024 * 1024 * 1024);
  double get vramUsedGb => vramUsedBytes / (1024 * 1024 * 1024);
}
