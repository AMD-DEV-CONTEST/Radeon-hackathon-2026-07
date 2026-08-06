#!/usr/bin/env bash
set -Eeuo pipefail

PARTS_DIR="${1:-.}"
RESTORE_ROOT="${2:-/persistent/buildguard}"

read -rsp "Recovery password: " BACKUP_PASSWORD
echo
export BACKUP_PASSWORD

cd "$PARTS_DIR"

sha256sum -c buildguard-unique-assets.SHA256SUMS

mkdir -p "$RESTORE_ROOT"

cat buildguard-unique-assets.tar.gz.enc.part-* \
| openssl enc \
    -d \
    -aes-256-cbc \
    -pbkdf2 \
    -iter 200000 \
    -pass env:BACKUP_PASSWORD \
| gzip -dc \
| tar \
    --numeric-owner \
    --xattrs \
    --acls \
    -C "$RESTORE_ROOT" \
    -xpf -

unset BACKUP_PASSWORD

echo "RESTORE COMPLETE: $RESTORE_ROOT"
