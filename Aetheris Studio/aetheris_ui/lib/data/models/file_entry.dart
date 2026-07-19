class FileEntry {
  final String name;
  final bool isDir;
  final int size;

  const FileEntry({required this.name, required this.isDir, this.size = 0});

  factory FileEntry.fromJson(Map<String, dynamic> json) => FileEntry(
        name: json['name']?.toString() ?? '',
        isDir: json['is_dir'] == true,
        size: (json['size'] as num?)?.toInt() ?? 0,
      );
}
