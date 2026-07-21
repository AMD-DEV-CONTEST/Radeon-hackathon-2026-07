import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/chat_provider.dart';
import '../providers/health_provider.dart';
import '../providers/project_provider.dart';
import '../providers/settings_provider.dart';
import '../theme.dart';
import 'settings_dialog.dart';

class SidebarScreen extends ConsumerWidget {
  const SidebarScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chatState = ref.watch(chatSessionsProvider);
    final health = ref.watch(healthProvider).valueOrNull;
    final settings = ref.watch(settingsProvider).valueOrNull;
    final projectPath = ref.watch(projectPathProvider).valueOrNull ?? '';

    return Container(
      color: AppColors.panel,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: () => ref.read(chatSessionsProvider.notifier).newChat(),
                    icon: const Icon(Icons.add, size: 16),
                    label: const Text('New chat'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.inputBg,
                      foregroundColor: AppColors.textPrimary,
                      elevation: 0,
                    ),
                  ),
                ),
                IconButton(
                  tooltip: 'Settings',
                  icon: const Icon(Icons.settings_outlined, size: 18, color: AppColors.textMuted),
                  onPressed: () => showDialog(context: context, builder: (_) => const SettingsDialog()),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: _ProjectFolderButton(projectPath: projectPath),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: chatState.loaded
                ? ListView.builder(
                    itemCount: chatState.chats.length,
                    itemBuilder: (context, i) {
                      final chat = chatState.chats[i];
                      final active = chat.id == chatState.activeChatId;
                      return ListTile(
                        dense: true,
                        selected: active,
                        selectedTileColor: AppColors.inputBg,
                        title: Text(
                          chat.title,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: active ? AppColors.accentGreen : AppColors.textPrimary,
                            fontSize: 13,
                          ),
                        ),
                        onTap: () => ref.read(chatSessionsProvider.notifier).switchChat(chat.id),
                        trailing: PopupMenuButton<String>(
                          icon: const Icon(Icons.more_vert, size: 16, color: AppColors.textMuted),
                          onSelected: (value) async {
                            if (value == 'rename') {
                              final controller = TextEditingController(text: chat.title);
                              final newTitle = await showDialog<String>(
                                context: context,
                                builder: (_) => AlertDialog(
                                  title: const Text('Rename chat'),
                                  content: TextField(controller: controller, autofocus: true),
                                  actions: [
                                    TextButton(
                                        onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
                                    TextButton(
                                        onPressed: () => Navigator.pop(context, controller.text),
                                        child: const Text('Save')),
                                  ],
                                ),
                              );
                              if (newTitle != null && newTitle.trim().isNotEmpty) {
                                await ref.read(chatSessionsProvider.notifier).renameChat(chat.id, newTitle.trim());
                              }
                            } else if (value == 'delete') {
                              await ref.read(chatSessionsProvider.notifier).deleteChat(chat.id);
                            }
                          },
                          itemBuilder: (context) => const [
                            PopupMenuItem(value: 'rename', child: Text('Rename')),
                            PopupMenuItem(value: 'delete', child: Text('Delete')),
                          ],
                        ),
                      );
                    },
                  )
                : const Center(child: CircularProgressIndicator(color: AppColors.accentGreen)),
          ),
          const Divider(height: 1, color: AppColors.border),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _StatusRow(label: 'SQLite', online: health?.sqliteOnline ?? false),
                const SizedBox(height: 6),
                Text(
                  settings?.defaultModel.isNotEmpty == true ? settings!.defaultModel : 'Nenhum modelo definido',
                  style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ProjectFolderButton extends ConsumerWidget {
  final String projectPath;

  const _ProjectFolderButton({required this.projectPath});

  String get _displayName {
    if (projectPath.isEmpty) return 'Select project folder...';
    final normalized = projectPath.replaceAll('\\', '/');
    final parts = normalized.split('/')..removeWhere((p) => p.isEmpty);
    return parts.isEmpty ? projectPath : parts.last;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return InkWell(
      onTap: () async {
        final picked = await FilePicker.platform.getDirectoryPath(dialogTitle: 'Select project folder');
        if (picked == null) return;
        final error = await ref.read(projectPathProvider.notifier).select(picked);
        if (error != null && context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Invalid path: $error'), backgroundColor: AppColors.accentRed),
          );
        }
      },
      borderRadius: BorderRadius.circular(6),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: AppColors.inputBg,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Row(
          children: [
            Icon(
              Icons.folder_open_outlined,
              size: 14,
              color: projectPath.isEmpty ? AppColors.textMuted : AppColors.accentGreen,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                _displayName,
                style: const TextStyle(color: AppColors.textPrimary, fontSize: 12),
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusRow extends StatelessWidget {
  final String label;
  final bool online;

  const _StatusRow({required this.label, required this.online});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: online ? AppColors.accentGreen : AppColors.accentRed,
          ),
        ),
        const SizedBox(width: 6),
        Text(label, style: const TextStyle(color: AppColors.textMuted, fontSize: 11)),
      ],
    );
  }
}
