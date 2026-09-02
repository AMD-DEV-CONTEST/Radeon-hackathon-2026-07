# Windows PowerShell 5.1 `-Encoding utf8` writes a BOM; tomllib rejects it

One-liner: never generate config files via PowerShell `Set-Content`/
`Out-File` on this dev box — they get a UTF-8 BOM and `tomllib.load`
fails with "Invalid statement (at line 1, column 1)".

Hit on July 16, 2026 creating pilot_4060.toml. Symptom is a confusing
parse error at 1:1 with visually valid TOML. Cause: PS 5.1's utf8 is
utf8-with-BOM (PowerShell 7 changed this, but the box runs 5.1 for tool
calls). Fix: write files with the editor/Write tool, or
`[IO.File]::WriteAllText(path, text)` which is BOM-free.

Also applies to anything Python reads in binary mode (tomllib, json in
"rb"), and to JSONL consumed by the trainer.
