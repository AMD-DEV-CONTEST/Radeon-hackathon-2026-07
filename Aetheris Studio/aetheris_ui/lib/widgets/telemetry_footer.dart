import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/models/app_state_models.dart';
import '../providers/egress_provider.dart';
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
    final egress = ref.watch(egressProvider).valueOrNull ?? const EgressState();

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
          _Divider(),
          _EgressIndicator(egress: egress),
        ],
      ),
    );
  }
}

/// Blackbox Egress Monitor (Fase B): "🔒 0 B external" when the sampler
/// sees only loopback connections, red + a count otherwise. Clicking
/// shows the observed connections (UC-02) -- never inventing a byte
/// figure the sampler can't actually measure (egress_monitor.py reports
/// `external_bytes: null` in that case, shown here as a connection count
/// instead).
class _EgressIndicator extends StatelessWidget {
  final EgressState egress;
  const _EgressIndicator({required this.egress});

  @override
  Widget build(BuildContext context) {
    final clean = egress.isClean;
    final label = !egress.sampling
        ? '\u{1F512} egress: --'
        : clean
            ? '\u{1F512} 0 B external'
            : '⚠ egress: ${egress.externalConnections.length}';
    return InkWell(
      onTap: () => _showDetails(context),
      child: Text(
        label,
        style: TextStyle(
          color: !egress.sampling ? AppColors.textMuted : (clean ? AppColors.accentGreen : AppColors.accentRed),
          fontSize: 10.5,
          fontFamily: AppFonts.mono,
        ),
      ),
    );
  }

  void _showDetails(BuildContext context) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AppColors.panel,
        title: const Text('Egress', style: TextStyle(color: AppColors.textPrimary, fontSize: 14)),
        content: SizedBox(
          width: 360,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${egress.loopbackCount} internal (UI ↔ backend ↔ vte-server) connection(s).',
                style: const TextStyle(color: AppColors.textMuted, fontSize: 12),
              ),
              const SizedBox(height: 8),
              if (egress.externalConnections.isEmpty)
                const Text('No external connections observed.',
                    style: TextStyle(color: AppColors.accentGreen, fontSize: 12))
              else
                ...egress.externalConnections.map(
                  (c) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Text(
                      '${c['raddr']} -- ${c['label']}',
                      style: const TextStyle(color: AppColors.accentRed, fontSize: 12, fontFamily: AppFonts.mono),
                    ),
                  ),
                ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close')),
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
