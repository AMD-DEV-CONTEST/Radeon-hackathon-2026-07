class FileSearchResult {
  final String path;
  final bool isDir;
  const FileSearchResult({required this.path, required this.isDir});

  factory FileSearchResult.fromJson(Map<String, dynamic> json) => FileSearchResult(
        path: json['path']?.toString() ?? '',
        isDir: json['is_dir'] == true,
      );
}
