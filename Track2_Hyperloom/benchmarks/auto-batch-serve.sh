#!/bin/bash
# auto-batch-serve.sh MODEL [PORT|sweep] [CTX_PER_SLOT]
#
# Auto-sizes continuous-batching parallelism (-np) for a llama.cpp model on
# gfx1201 GPU0, then launches llama-server with continuous batching. The optimal
# -np is PER-MODEL (measured: 8B ternary peaks ~13x at np~96 with a cliff at 128;
# 27B ternary only ~4.6x, plateaus ~np48) so it MUST be measured, not guessed.
#
# Pipeline: VRAM-bounded search  ->  clock-pinned reliable sweep (ntg=128)  ->
#           throughput-knee detection (peak, but stop at the flat tail / before
#           the over-subscription cliff)  ->  disk-cache  ->  launch server.
#
# PORT=sweep  -> only compute+print the chosen -np, don't launch (for testing).
set -u
MODEL="${1:?usage: auto-batch-serve.sh MODEL [PORT|sweep] [CTX_PER_SLOT]}"
PORT="${2:-8100}"
CTX="${3:-4096}"
# Point FORK at a checkout of https://github.com/The-Monk/llama.cpp (branch roc8)
FORK="${FORK:?set FORK to your llama.cpp checkout}"
BIN="${BIN:-$FORK/build/bin}"
CARD=/sys/class/drm/card1/device/power_dpm_force_performance_level   # GPU0 (04:00.0)
CACHE="$HOME/.cache/auto-batch-np.tsv"
VRAM_TOTAL=34208743424   # R9700 32 GiB
source "$FORK/use-rocm714.env" 2>/dev/null
export HIP_VISIBLE_DEVICES=0
NP=""

KEY="$(basename "$MODEL")|ctx${CTX}"

# ---- 0. cache: (model, ctx) -> np (skip the sweep on a hit) --------------------
if [ -f "$CACHE" ]; then
    c=$(awk -F'\t' -v k="$KEY" '$1==k{print $2; exit}' "$CACHE")
    [ -n "$c" ] && { NP="$c"; echo "[auto-batch] cache hit: -np $NP for $KEY"; }
fi

if [ -z "$NP" ]; then
    # ---- 1. KV-bounded -np ceiling (so the sweep never OOMs) -------------------
    read -r NL NHKV HD < <(PYTHONPATH="$FORK/gguf-py" python3 - "$MODEL" <<'PY' 2>/dev/null
import sys
from gguf import GGUFReader
r=GGUFReader(sys.argv[1])
def g(*ks):
    for f in r.fields.values():
        for k in ks:
            if f.name.endswith(k):
                try: return int(f.parts[f.data[0]][0])
                except: pass
    return 0
nl=g('block_count'); nhkv=g('attention.head_count_kv') or g('attention.head_count')
nh=g('attention.head_count') or 1; ne=g('embedding_length')
hd=g('attention.key_length') or (ne//nh if nh else 128)
print(nl or 64, nhkv or 8, hd or 128)
PY
)
    NL=${NL:-64}; NHKV=${NHKV:-8}; HD=${HD:-128}
    used=$(rocm-smi --showmeminfo vram 2>/dev/null | grep -oE 'GPU\[0\].*Used Memory \(B\): [0-9]+' | grep -oE '[0-9]+$' | head -1)
    free=$(( VRAM_TOTAL - ${used:-0} ))
    mdl=$(stat -c%s "$MODEL")
    kv_slot=$(( 2 * NL * NHKV * HD * 2 * CTX ))            # 2(K+V) * layers * kv_heads * head_dim * 2B(fp16) * ctx
    avail=$(( free - mdl - 2*1024*1024*1024 ))             # reserve 2 GiB for compute buffers
    npmax=$(( avail / kv_slot )); [ "$npmax" -lt 1 ] && npmax=1; [ "$npmax" -gt 256 ] && npmax=256
    echo "[auto-batch] model dims: n_layer=$NL n_head_kv=$NHKV head_dim=$HD | KV/slot@${CTX}=$((kv_slot/1024/1024))MB | VRAM-max -np=$npmax"

    # ---- 2. reliable sweep: pinned clock (stable ratios) + ntg=128 -------------
    grid=""; for n in 1 8 16 32 48 64 96 128 192 256; do [ "$n" -le "$npmax" ] && grid="$grid,$n"; done
    grid="${grid#,}"; [ -z "$grid" ] && grid=1
    maxn=$(echo "$grid" | tr ',' '\n' | tail -1)
    sweepc=$(( maxn * (32 + 128) + 512 ))
    echo "high" | sudo tee "$CARD" >/dev/null 2>&1
    echo "[auto-batch] sweeping npl=$grid (ntg=128, clocks pinned high)..."
    out=$("$BIN/llama-batched-bench" -m "$MODEL" -c "$sweepc" -b 2048 -ub 512 \
            -npp 32 -ntg 128 -npl "$grid" -ngl 99 2>/dev/null | grep -E '^\|')
    echo "auto" | sudo tee "$CARD" >/dev/null 2>&1

    # ---- 3. knee detection: peak throughput, but stop at the flat tail / before
    #         the cliff (first np whose next step gains < 3%; else the true peak) -
    NP=$(echo "$out" | awk -F'|' '
        {b=$4+0; tg=$9+0; if(b>0&&tg>0){n[++k]=b; s[k]=tg;
            printf "    -np %-4d  S_TG=%6.0f t/s  (%.1f/stream)\n", b, tg, tg/b > "/dev/stderr"}}
        END{
            if(k==0){print 1; exit}
            best=1; bt=0; for(i=1;i<=k;i++) if(s[i]>bt){bt=s[i]; best=n[i]}   # true peak (cliff-safe: argmax)
            knee=best
            for(i=1;i<k;i++){ if(s[i+1]/s[i]-1 < 0.03){ knee=n[i]; break } } # flat-tail / pre-cliff knee
            print knee
        }')
    [ -z "$NP" ] && NP=1
    echo "[auto-batch] chosen -np $NP  (throughput knee; peak-aware, cliff-safe)"
    mkdir -p "$(dirname "$CACHE")"; printf "%s\t%s\n" "$KEY" "$NP" >> "$CACHE"
    echo "[auto-batch] cached -> $CACHE"
fi

# ---- 4. launch (or sweep-only) ------------------------------------------------
SERVE_C=$(( NP * CTX ))
echo "[auto-batch] serving config: -np $NP  -c $SERVE_C  (${CTX} ctx/slot)  continuous-batching  GPU0"
if [ "$PORT" = "sweep" ]; then echo "[auto-batch] sweep-only mode; not launching."; exit 0; fi
echo "[auto-batch] launching llama-server on 127.0.0.1:$PORT ..."
exec "$BIN/llama-server" -m "$MODEL" -np "$NP" -c "$SERVE_C" \
     --cont-batching -ngl 99 --host 127.0.0.1 --port "$PORT"
