const LANG_MAP: Record<string, string> = {
  py: "python",
  rs: "rust",
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  go: "go",
  toml: "toml",
  json: "json",
  md: "markdown",
  sh: "shell",
  css: "css",
};

export function languageForPath(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  return LANG_MAP[ext] ?? "plaintext";
}
