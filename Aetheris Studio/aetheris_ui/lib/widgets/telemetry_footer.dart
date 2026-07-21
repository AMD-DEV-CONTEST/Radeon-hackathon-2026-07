import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/models/app_state_models.dart';
import '../providers/telemetry_provider.dart';
import '../theme.dart';

/// Thin status-bar footer (VSCode-style: 22px, small mono text) showing
/// real GPU telemetry, not placeholders: connection state, GPU name, VRAM
/// used/total, and the last measured decode speed. Every number comes
/// straight from telemetryProvider's poll of GET /api/telemetry, itself a
/// live hipMemGetInfo read on the vte-server side.
class TelemetryFooter extends ConsumerWidget {
  const TelemetryFooter({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final telemetry = ref.watch(telemetryProvider).valueOrNull ?? const TelemetryState();

    return Container(
      height: 22,
      color: AppColors.panel,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      child: Row(
        children: [
          _ConnectionDot(connected: telemetry.connected),
          const SizedBox(width: 6),
          _Segment(text: telemetry.connected ? 'VTE' : 'VTE disconnected'),
          if (telemetry.connected) ...[
            _Divider(),
            _Segment(text: telemetry.displayGpuName),
            _Divider(),
            _Segment(
              text: 'VRAM ${telemetry.vramUsedGb.toStringAsFixed(1)}/${telemetry.vramTotalGb.toStringAsFixed(1)} GB',
            ),
            _Divider(),
            _Segment(text: '${telemetry.decodingSpeedTps.toStringAsFixed(1)} tok/s'),
          ],
        ],
      ),
    );
  }
}

class _ConnectionDot extends StatelessWidget {
  final bool connected;
  const _ConnectionDot({required this.connected});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 6,
      height: 6,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: connected ? AppColors.accentGreen : AppColors.accentRed,
      ),
    );
  }
}

class _Segment extends StatelessWidget {
  final String text;
  const _Segment({required this.text});

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        color: AppColors.textMuted,
        fontSize: 10.5,
        fontFamily: AppFonts.mono,
        fontFeatures: [FontFeature.tabularFigures()],
      ),
      overflow: TextOverflow.ellipsis,
    );
  }
}

class _Divider extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.symmetric(horizontal: 8),
      child: Text('|', style: TextStyle(color: AppColors.border, fontSize: 10.5)),
    );
  }
}
