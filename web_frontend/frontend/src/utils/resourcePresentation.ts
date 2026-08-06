export type ResourceKind =
  | 'directory'
  | 'code'
  | 'markdown'
  | 'text'
  | 'config'
  | 'data'
  | 'image'
  | 'pdf'
  | 'document'
  | 'spreadsheet'
  | 'presentation'
  | 'archive'
  | 'audio'
  | 'video'
  | 'binary'
  | 'url'

export interface ResourcePresentation {
  kind: ResourceKind
  extension: string
  iconClass: string
  typeLabel: string
}

const ICON_PREFIX = 'i-vscode-icons-'

const EXTENSION_PRESENTATIONS: Record<string, Omit<ResourcePresentation, 'extension'>> = {
  py: icon('code', 'file-type-python', 'Python'),
  js: icon('code', 'file-type-js', 'JavaScript'),
  mjs: icon('code', 'file-type-js', 'JavaScript'),
  cjs: icon('code', 'file-type-js', 'JavaScript'),
  ts: icon('code', 'file-type-typescript', 'TypeScript'),
  tsx: icon('code', 'file-type-reactts', 'React TypeScript'),
  jsx: icon('code', 'file-type-reactjs', 'React JavaScript'),
  vue: icon('code', 'file-type-vue', 'Vue'),
  rs: icon('code', 'file-type-rust', 'Rust'),
  go: icon('code', 'file-type-go', 'Go'),
  java: icon('code', 'file-type-java', 'Java'),
  c: icon('code', 'file-type-c', 'C'),
  h: icon('code', 'file-type-c', 'C Header'),
  cc: icon('code', 'file-type-cpp', 'C++'),
  cpp: icon('code', 'file-type-cpp', 'C++'),
  hpp: icon('code', 'file-type-cpp', 'C++ Header'),
  cs: icon('code', 'file-type-csharp', 'C#'),
  swift: icon('code', 'file-type-swift', 'Swift'),
  kt: icon('code', 'file-type-kotlin', 'Kotlin'),
  html: icon('code', 'file-type-html', 'HTML'),
  htm: icon('code', 'file-type-html', 'HTML'),
  css: icon('code', 'file-type-css', 'CSS'),
  scss: icon('code', 'file-type-sass', 'Sass'),
  sass: icon('code', 'file-type-sass', 'Sass'),
  sql: icon('code', 'file-type-sql', 'SQL'),
  sh: icon('code', 'file-type-shell', 'Shell'),
  bash: icon('code', 'file-type-shell', 'Shell'),
  zsh: icon('code', 'file-type-shell', 'Shell'),
  ps1: icon('code', 'file-type-powershell', 'PowerShell'),
  json: icon('config', 'file-type-json', 'JSON'),
  jsonl: icon('data', 'file-type-json', 'JSON Lines'),
  yaml: icon('config', 'file-type-yaml', 'YAML'),
  yml: icon('config', 'file-type-yaml', 'YAML'),
  toml: icon('config', 'file-type-toml', 'TOML'),
  xml: icon('config', 'file-type-xml', 'XML'),
  md: icon('markdown', 'file-type-markdown', 'Markdown'),
  markdown: icon('markdown', 'file-type-markdown', 'Markdown'),
  mdx: icon('markdown', 'file-type-markdown', 'MDX'),
  txt: icon('text', 'file-type-text', 'Text'),
  log: icon('text', 'file-type-log', 'Log'),
  csv: icon('spreadsheet', 'file-type-excel', 'CSV'),
  tsv: icon('spreadsheet', 'file-type-excel', 'TSV'),
  xls: icon('spreadsheet', 'file-type-excel', 'Excel'),
  xlsx: icon('spreadsheet', 'file-type-excel', 'Excel'),
  doc: icon('document', 'file-type-word', 'Word'),
  docx: icon('document', 'file-type-word', 'Word'),
  rtf: icon('document', 'file-type-word', 'RTF'),
  ppt: icon('presentation', 'file-type-powerpoint', 'PowerPoint'),
  pptx: icon('presentation', 'file-type-powerpoint', 'PowerPoint'),
  pdf: icon('pdf', 'file-type-pdf2', 'PDF'),
  png: icon('image', 'file-type-image', 'PNG'),
  jpg: icon('image', 'file-type-image', 'JPEG'),
  jpeg: icon('image', 'file-type-image', 'JPEG'),
  gif: icon('image', 'file-type-image', 'GIF'),
  svg: icon('image', 'file-type-image', 'SVG'),
  webp: icon('image', 'file-type-image', 'WebP'),
  bmp: icon('image', 'file-type-image', 'Bitmap'),
  tif: icon('image', 'file-type-image', 'TIFF'),
  tiff: icon('image', 'file-type-image', 'TIFF'),
  heic: icon('image', 'file-type-image', 'HEIC'),
  mp3: icon('audio', 'file-type-audio', 'MP3'),
  wav: icon('audio', 'file-type-audio', 'WAV'),
  m4a: icon('audio', 'file-type-audio', 'M4A'),
  flac: icon('audio', 'file-type-audio', 'FLAC'),
  mp4: icon('video', 'file-type-video', 'MP4'),
  mov: icon('video', 'file-type-video', 'QuickTime'),
  webm: icon('video', 'file-type-video', 'WebM'),
  avi: icon('video', 'file-type-video', 'AVI'),
  zip: icon('archive', 'file-type-zip', 'ZIP'),
  gz: icon('archive', 'file-type-zip', 'GZip'),
  tgz: icon('archive', 'file-type-zip', 'GZip'),
  tar: icon('archive', 'file-type-zip', 'TAR'),
  '7z': icon('archive', 'file-type-zip', '7-Zip'),
  rar: icon('archive', 'file-type-zip', 'RAR'),
}

const MIME_KIND_PRESENTATIONS: Array<[string, Omit<ResourcePresentation, 'extension'>]> = [
  ['image/', icon('image', 'file-type-image', 'Image')],
  ['audio/', icon('audio', 'file-type-audio', 'Audio')],
  ['video/', icon('video', 'file-type-video', 'Video')],
  ['application/pdf', icon('pdf', 'file-type-pdf2', 'PDF')],
  ['text/', icon('text', 'file-type-text', 'Text')],
]

export const RESOURCE_ICON_CLASSES = Array.from(new Set([
  `${ICON_PREFIX}default-file`,
  `${ICON_PREFIX}default-folder`,
  `${ICON_PREFIX}default-folder-opened`,
  ...Object.values(EXTENSION_PRESENTATIONS).map(presentation => presentation.iconClass),
  ...MIME_KIND_PRESENTATIONS.map(([, presentation]) => presentation.iconClass),
]))

export const CODE_EXTENSIONS = new Set(
  Object.entries(EXTENSION_PRESENTATIONS)
    .filter(([, presentation]) => presentation.kind === 'code')
    .map(([extension]) => extension),
)

export const IMAGE_EXTENSIONS = new Set(
  Object.entries(EXTENSION_PRESENTATIONS)
    .filter(([, presentation]) => presentation.kind === 'image')
    .map(([extension]) => extension),
)

export function resourceExtension(name: string): string {
  const normalized = String(name || '').replace(/\\/g, '/').split('/').pop() || ''
  const separator = normalized.lastIndexOf('.')
  return separator > 0 ? normalized.slice(separator + 1).toLowerCase() : ''
}

export function resourcePresentation(options: {
  name: string
  mimeType?: string | null
  kind?: 'file' | 'directory' | 'url' | string | null
  expanded?: boolean
}): ResourcePresentation {
  const extension = resourceExtension(options.name)
  if (options.kind === 'directory') {
    return {
      kind: 'directory',
      extension: '',
      iconClass: `${ICON_PREFIX}${options.expanded ? 'default-folder-opened' : 'default-folder'}`,
      typeLabel: 'Folder',
    }
  }
  if (options.kind === 'url') {
    return {
      kind: 'url',
      extension: '',
      iconClass: `${ICON_PREFIX}default-file`,
      typeLabel: 'URL',
    }
  }
  const byExtension = EXTENSION_PRESENTATIONS[extension]
  if (byExtension) return { ...byExtension, extension }

  const mimeType = String(options.mimeType || '').toLowerCase()
  const byMime = MIME_KIND_PRESENTATIONS.find(([prefix]) => mimeType.startsWith(prefix))?.[1]
  if (byMime) return { ...byMime, extension }

  return {
    kind: mimeType ? 'binary' : 'text',
    extension,
    iconClass: `${ICON_PREFIX}${mimeType ? 'file-type-binary' : 'default-file'}`,
    typeLabel: extension ? extension.toUpperCase() : 'File',
  }
}

function icon(
  kind: ResourceKind,
  iconName: string,
  typeLabel: string,
): Omit<ResourcePresentation, 'extension'> {
  return {
    kind,
    iconClass: `${ICON_PREFIX}${iconName}`,
    typeLabel,
  }
}
