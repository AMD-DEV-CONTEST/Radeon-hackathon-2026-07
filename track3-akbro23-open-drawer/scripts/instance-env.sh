# Environment for the ROCm instance. Run once per container:
#
#   source scripts/instance-env.sh
#
# It adds itself to ~/.bashrc, so later shells pick it up. /root is the
# container's overlay and does not survive a restart; /persistent does, this
# repo included. Everything mirror- or instance-specific lives here and nowhere
# else, so a checkout anywhere else behaves normally by doing nothing.

# BASH_SOURCE, not $0: this file is sourced rather than executed.
_self="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
_root="$(cd "$(dirname "$_self")/.." && pwd)"

PERSIST="${PERSIST:-/persistent}"

# On the same filesystem as the venv, or installs copy instead of hardlinking.
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PERSIST/.uv-cache}"
# pi0.5 plus the PaliGemma tokenizer -- several GB, not worth fetching twice.
export HF_HOME="${HF_HOME:-$PERSIST/.hf}"

# Both mirrors replace their upstream rather than joining it. UV_DEFAULT_INDEX
# decides the URLs written into uv.lock, so check `grep -c pypi.org uv.lock`
# before committing a lock made in a shell that may not have sourced this.
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

# Secrets. Gitignored; see .env.example. `set -a` exports what it defines.
if [ -f "$_root/.env" ]; then
    set -a; . "$_root/.env"; set +a
fi

if ! grep -qsF "$_self" ~/.bashrc; then
    printf '\n# open-drawer instance environment\nsource %s\n' "$_self" >> ~/.bashrc
    echo "added to ~/.bashrc: source $_self"
fi

# Reports whether a secret is present WITHOUT printing it. Note that the
# obvious one-liner leaks: "${TOKEN:+set}${TOKEN:-MISSING}" expands to "set"
# concatenated with the token's value whenever it is set, so the summary below
# would echo the secret into the terminal and the shell history.
_status() { if [ -n "$1" ]; then echo set; else echo MISSING; fi; }

echo "uv    cache=$UV_CACHE_DIR  index=$UV_DEFAULT_INDEX"
echo "hf    home=$HF_HOME  endpoint=$HF_ENDPOINT  token=$(_status "$HF_TOKEN")"
echo "wandb token=$(_status "$WANDB_API_KEY")"
unset _self _root
unset -f _status
