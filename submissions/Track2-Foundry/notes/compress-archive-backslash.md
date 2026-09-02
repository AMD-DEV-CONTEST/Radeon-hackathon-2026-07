# Compress-Archive zips break on Linux: backslash entry paths

One-liner: never ship a PowerShell `Compress-Archive` zip to a Linux
box — it stores entry names with `\` separators, so Python's zipfile
extracts `foundry\config.py` as a flat junk *file* instead of creating
directories, and imports fail with ModuleNotFoundError.

Hit July 17, 2026 transferring the repo to the Radeon instance. Fix:
use Windows' built-in bsdtar instead —

    tar --exclude "__pycache__" -czf transfer.tar.gz <dirs...>

which writes POSIX paths and extracts cleanly with plain `tar -xzf`
(bonus: the instance lacks `unzip` anyway). Sibling lesson to
[[windows-powershell-bom]]: PS 5.1 artifacts default to Windows-isms;
anything consumed by Linux/Python needs a portability check.
