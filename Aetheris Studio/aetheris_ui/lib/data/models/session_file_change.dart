/// One write_file/edit_file the agent actually executed this session
/// (post-approval -- see ChatSessionsNotifier.respondToolConfirm).
class SessionFileChange {
  final String path;
  final String tool;
  final DateTime timestamp;

  const SessionFileChange({
    required this.path,
    required this.tool,
    required this.timestamp,
  });
}
