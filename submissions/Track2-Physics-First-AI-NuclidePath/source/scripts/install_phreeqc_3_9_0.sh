#!/usr/bin/env bash
set -Eeuo pipefail

readonly RELEASE='3.9.0-17591'
readonly ARCHIVE="phreeqc-${RELEASE}.tar.gz"
readonly URL="https://github.com/phreeqc-dev/phreeqc3/releases/download/v3.9.0/${ARCHIVE}"
readonly ARCHIVE_SHA256='fda26290d96f6785e440c05217bf4b9fa9cd1efbf2fee155591e05b30165c6cd'
readonly DATABASE_SHA256='5b80d45c989cd1db7aab485e198321ba550d5902be8097c8be26d85ba03da278'

[[ $# -eq 1 ]] || { echo "usage: $0 /absolute/destination" >&2; exit 2; }
DESTINATION=$1
[[ "$DESTINATION" = /* ]] || { echo 'destination must be absolute' >&2; exit 2; }
[[ ! -L "$DESTINATION" ]] || { echo 'destination must not be a symlink' >&2; exit 2; }
mkdir -p "$DESTINATION"
DESTINATION=$(cd "$DESTINATION" && pwd -P)
for directory in download source build install; do
  [[ ! -e "$DESTINATION/$directory" ]] || { echo "refusing existing path: $DESTINATION/$directory" >&2; exit 2; }
  mkdir "$DESTINATION/$directory"
done

TEMP_ARCHIVE=$(mktemp "$DESTINATION/download/.${ARCHIVE}.XXXXXX")
trap 'rm -f "$TEMP_ARCHIVE"' EXIT
curl --fail --location --proto '=https' --tlsv1.2 "$URL" --output "$TEMP_ARCHIVE"
printf '%s  %s\n' "$ARCHIVE_SHA256" "$TEMP_ARCHIVE" | sha256sum --check --strict
mv "$TEMP_ARCHIVE" "$DESTINATION/download/$ARCHIVE"
trap - EXIT

# Reject absolute paths, parent traversal, and archive links before extracting.
python3 - "$DESTINATION/download/$ARCHIVE" "$DESTINATION/source" <<'PY'
import pathlib, sys, tarfile
def _safe_filter(member, path):
    if member.issym() or member.islnk():
        raise tarfile.FilterError(f"link member rejected: {member.name}")
    if not (member.isfile() or member.isdir()):
        raise tarfile.FilterError(f"special member rejected: {member.name}")
    return member
archive, destination = sys.argv[1:]
with tarfile.open(archive, "r:gz") as stream:
    for member in stream.getmembers():
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
            raise SystemExit(f"unsafe archive member: {member.name}")
    stream.extractall(destination, filter=_safe_filter)
PY

SOURCE="$DESTINATION/source/phreeqc-$RELEASE"
[[ -d "$SOURCE" && ! -L "$SOURCE" ]] || { echo 'expected source directory unavailable' >&2; exit 2; }
# The release's Autoconf build is performed out-of-tree with an explicit prefix.
# Binary hashes describe this exact toolchain/build and are not portable promises.
(
  cd "$DESTINATION/build"
  "$SOURCE/configure" --prefix="$DESTINATION/install"
  make -j1
  make install
)

EXECUTABLE="$DESTINATION/install/bin/phreeqc"
DATABASE="$DESTINATION/install/share/doc/phreeqc/database/phreeqc.dat"
EXAMPLE="$DESTINATION/install/share/doc/phreeqc/examples/ex2"
for file in "$EXECUTABLE" "$DATABASE" "$EXAMPLE"; do
  [[ -f "$file" && ! -L "$file" ]] || { echo "invalid installed file: $file" >&2; exit 2; }
done
printf '%s  %s\n' "$DATABASE_SHA256" "$DATABASE" | sha256sum --check --strict

PROBE="$DESTINATION/build/banner-probe"
mkdir "$PROBE"
(
  cd "$PROBE"
  LANG=C LC_ALL=C "$EXECUTABLE" "$EXAMPLE" output.txt "$DATABASE" phreeqc.log >/dev/null 2>&1
)
VERSION=$(sed -n 's/.*PHREEQC_\([0-9][0-9.]*\).*/\1/p' "$PROBE/phreeqc.log" | head -1)
DATE=$(sed -n 's/.*\([A-Z][a-z]* [0-9][0-9]*, [0-9][0-9][0-9][0-9]\).*/\1/p' "$PROBE/phreeqc.log" | head -1)
[[ -n "$VERSION" && -n "$DATE" ]] || { echo 'unable to obtain PHREEQC banner' >&2; exit 2; }

printf 'Executable: %s\n' "$EXECUTABLE"
printf 'Database: %s\n' "$DATABASE"
printf 'Banner: PHREEQC %s, %s\n' "$VERSION" "$DATE"
printf 'Executable SHA-256: %s\n' "$(sha256sum "$EXECUTABLE" | awk '{print $1}')"
printf 'Database SHA-256: %s\n' "$(sha256sum "$DATABASE" | awk '{print $1}')"
printf 'Compiler: %s\n' "$(c++ --version | head -1)"
printf 'Make: %s\n' "$(make --version | head -1)"
printf '%s\n' 'Note: the executable hash is specific to this toolchain and build environment.'
