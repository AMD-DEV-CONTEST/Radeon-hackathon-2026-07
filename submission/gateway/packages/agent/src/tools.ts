// OpenAI-compatible tool definitions for DeepSeek function calling
export type ToolName =
  | 'read_file'
  | 'write_file'
  | 'edit_file'
  | 'delete_file'
  | 'list_dir'
  | 'run_command'
  | 'search_files'
  | 'create_dir';

export const TOOL_DEFINITIONS = [
  {
    type: 'function' as const,
    function: {
      name: 'read_file',
      description: 'Read the contents of a file inside the task workspace.',
      parameters: {
        type: 'object',
        properties: {
          path: { type: 'string', description: 'Relative path from workspace root' },
        },
        required: ['path'],
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'write_file',
      description: 'Write (or overwrite) a file inside the task workspace.',
      parameters: {
        type: 'object',
        properties: {
          path:    { type: 'string', description: 'Relative path from workspace root' },
          content: { type: 'string', description: 'Full file content to write' },
        },
        required: ['path', 'content'],
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'edit_file',
      description: 'Replace exact text in a file (search-and-replace). old_str must be unique.',
      parameters: {
        type: 'object',
        properties: {
          path:    { type: 'string', description: 'Relative path from workspace root' },
          old_str: { type: 'string', description: 'Exact text to find (must be unique in file)' },
          new_str: { type: 'string', description: 'Replacement text' },
        },
        required: ['path', 'old_str', 'new_str'],
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'delete_file',
      description: 'Delete a file inside the task workspace.',
      parameters: {
        type: 'object',
        properties: {
          path: { type: 'string', description: 'Relative path from workspace root' },
        },
        required: ['path'],
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'list_dir',
      description: 'List files and subdirectories inside the task workspace.',
      parameters: {
        type: 'object',
        properties: {
          path: { type: 'string', description: 'Relative path from workspace root (default ".")' },
        },
        required: [],
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'run_command',
      description: 'Execute a shell command inside the task workspace. Returns stdout+stderr.',
      parameters: {
        type: 'object',
        properties: {
          command: { type: 'string', description: 'Shell command to execute' },
          cwd:     { type: 'string', description: 'Working dir relative to workspace root (default: workspace root)' },
          timeout: { type: 'number', description: 'Timeout in seconds (default 120, max 600)' },
        },
        required: ['command'],
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'search_files',
      description: 'Search for files matching a glob pattern inside the task workspace.',
      parameters: {
        type: 'object',
        properties: {
          pattern: { type: 'string', description: 'Glob pattern e.g. "src/**/*.ts"' },
          path:    { type: 'string', description: 'Search root relative to workspace (default ".")' },
        },
        required: ['pattern'],
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'create_dir',
      description: 'Create a directory (and parents) inside the task workspace.',
      parameters: {
        type: 'object',
        properties: {
          path: { type: 'string', description: 'Relative path from workspace root' },
        },
        required: ['path'],
      },
    },
  },
];
