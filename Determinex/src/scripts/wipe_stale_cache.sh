#!/bin/bash
# wipe_stale_cache.sh — wipe Hetzner ProgramBench cache when scaffolds change.
# Run after every scaffold-affecting commit to invalidate stale builds.
#
# Modes:
#   ./wipe_stale_cache.sh                 # wipe ALL determinex-cached
#   ./wipe_stale_cache.sh tool_id ...     # wipe specific tools only
#   ./wipe_stale_cache.sh --older-than 2h # wipe images older than 2 hours
#
# Future (with v2 patch): wipe by submission hash mismatch.
set -uo pipefail

HETZNER="${HETZNER:-root@5.78.192.163}"
KEY="${KEY:-$HOME/.ssh/id_determinex}"
MODE="all"
if [ "${1:-}" = "--older-than" ]; then
    MODE="age"
    AGE="${2:-2h}"
elif [ -n "${1:-}" ]; then
    MODE="tools"
    TOOLS="$@"
fi

case "$MODE" in
    all)
        echo "Wiping ALL determinex-cached images..."
        ssh -i "$KEY" "$HETZNER" 'docker images --format "{{.Repository}}:{{.Tag}}" | grep "determinex-cached" | xargs -r docker rmi -f 2>&1 | tail -3'
        ;;
    age)
        echo "Wiping determinex-cached images older than $AGE..."
        ssh -i "$KEY" "$HETZNER" "docker images --format '{{.ID}}\t{{.Tag}}\t{{.CreatedSince}}' | grep -E 'determinex-(cached|[a-f0-9]{12})' | awk '/$AGE|day|week|month/ {print \$1}' | xargs -r docker rmi -f 2>&1 | tail -3"
        ;;
    tools)
        for tool in $TOOLS; do
            echo "Wiping cached images for $tool..."
            ssh -i "$KEY" "$HETZNER" "docker images --format '{{.Repository}}:{{.Tag}}' | grep 'programbench-compiled/$tool' | xargs -r docker rmi -f 2>&1 | tail -1"
        done
        ;;
esac

echo "Done. Remaining cached images: $(ssh -i "$KEY" "$HETZNER" 'docker images | grep -c determinex')"
