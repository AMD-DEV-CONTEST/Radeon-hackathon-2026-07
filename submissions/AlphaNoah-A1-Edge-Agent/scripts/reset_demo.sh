#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="$ROOT/data/alphanoah-demo.sqlite3"
[[ -e "$DB" ]] || { echo "Demo database is already clean."; exit 0; }
[[ -f "$DB" && ! -L "$DB" ]] || { echo "Refusing unsafe demo database target."; exit 1; }
mv "$DB" "$DB.reset.$(date +%Y%m%d%H%M%S)"
echo "Demo database reset; recoverable backup retained in data/."
