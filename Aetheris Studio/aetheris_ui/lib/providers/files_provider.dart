import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/api_client.dart';
import '../data/models/file_entry.dart';
import 'api_provider.dart';
import 'project_provider.dart';

class FilesState {
  final String root;
  final String path; // relative to root, '' = project root
  final List<FileEntry> entries;
  final String? error;

  const FilesState({this.root = '', this.path = '', this.entries = const [], this.error});
}

/// Browses the active project's folder tree (Fase 4.5 Inspector "Arquivos"
/// tab) -- one directory level at a time, via GET /api/files/list.
class FilesNotifier extends StateNotifier<FilesState> {
  final ApiClient _api;
  FilesNotifier(this._api) : super(const FilesState());

  Future<void> open(String relativePath) async {
    try {
      final json = await _api.listProjectFiles(path: relativePath);
      final entries =
          (json['entries'] as List).map((e) => FileEntry.fromJson(e as Map<String, dynamic>)).toList();
      state = FilesState(
        root: json['root']?.toString() ?? '',
        path: json['path']?.toString() ?? '',
        entries: entries,
      );
    } on ApiException catch (e) {
      state = FilesState(root: state.root, path: state.path, error: e.message);
    } catch (e) {
      state = FilesState(root: state.root, path: state.path, error: e.toString());
    }
  }

  Future<void> openSubfolder(String name) async {
    final next = state.path.isEmpty ? name : '${state.path}/$name';
    await open(next);
  }

  Future<void> openParent() async {
    if (state.path.isEmpty) return;
    final parts = state.path.split('/')..removeLast();
    await open(parts.join('/'));
  }
}

final filesProvider = StateNotifierProvider<FilesNotifier, FilesState>((ref) {
  final notifier = FilesNotifier(ref.watch(apiClientProvider));
  // Reload the file tree whenever the active project changes.
  ref.listen(projectPathProvider, (prev, next) {
    next.whenData((path) {
      if (path.isNotEmpty) notifier.open('');
    });
  });
  return notifier;
});
