#!/usr/bin/env bash
#
# 把"重启后无法自动重建"的东西收进 NFS 持久化目录。
#
# 平台维护窗口前跑这个。它只处理三类真正会丢的东西：
#
#   1. SQLite 一致性快照 —— 后端在线时直接 cp poster.db 是错的：WAL 里可能有
#      几 MB 尚未 checkpoint 的数据，拷出来的文件要么旧要么撕裂。用 VACUUM INTO
#      取读快照，产出单文件（已并入 WAL、已压紧），再跑一次 integrity_check。
#   2. .env —— 被 .gitignore 排除，所以它是全机唯一副本。丢了要重新推导
#      DB_PATH / 各 STORAGE_ROOT / REFERENCE_CONTROL_PATCH 这一串。
#   3. 权重清单 —— 43G 的模型不可能塞进备份（盘上就没那么多空余），但清单能让
#      重新下载有个校对依据。这一条不是形式主义：hf-mirror 的 Xet 大文件会绕过
#      镜像直连 cas-server.xethub.hf.co 然后 401，留下一个"看着像好的"目录。
#      那次就是靠核对文件大小才发现的。
#
# storage/ 和 data/ 本身已经在持久化目录里了，脚本不去重复搬运。
#
# 用法：
#   bash scripts/backup-persistence.sh              # 快速（不算哈希）
#   bash scripts/backup-persistence.sh --hash       # 附带 sha256，慢，43G 要几分钟

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PERSIST_ROOT="${PERSIST_ROOT:-/workspace/persistence/stageposter}"

WITH_HASH=0
if [[ "${1:-}" == "--hash" ]]; then
    WITH_HASH=1
fi

STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
BACKUP_DIR="${PERSIST_ROOT}/backups/${STAMP}"

mkdir -p "${BACKUP_DIR}"

echo "==> 备份目录 ${BACKUP_DIR}"

# ---------------------------------------------------------------- 1. 数据库

# DB_PATH 从 .env 读，不要在这里硬编码：仓库里还留着一个陈旧的
# backend/data/poster.db，照默认值备份会悄悄备份错的那个。
DB_PATH=""
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    DB_PATH="$(grep -E '^DB_PATH=' "${PROJECT_ROOT}/.env" | tail -1 | cut -d= -f2- || true)"
fi
DB_PATH="${DB_PATH:-${PERSIST_ROOT}/data/poster.db}"

if [[ -f "${DB_PATH}" ]]; then
    echo "==> SQLite 快照 ${DB_PATH}"

    if ! sqlite3 "${DB_PATH}" "VACUUM INTO '${BACKUP_DIR}/poster.db';" 2>/dev/null; then
        echo "    VACUUM INTO 失败，退回在线备份 API"
        sqlite3 "${DB_PATH}" ".backup '${BACKUP_DIR}/poster.db'"
    fi

    # 校验快照本身，而不是校验源库 —— 我们要断言的是"这个备份能用"。
    INTEGRITY="$(sqlite3 "${BACKUP_DIR}/poster.db" 'PRAGMA integrity_check;')"
    echo "    integrity_check: ${INTEGRITY}"
    if [[ "${INTEGRITY}" != "ok" ]]; then
        echo "!!! 快照损坏，不要依赖它" >&2
        exit 1
    fi

    # 逐表计数，表名从 sqlite_master 现取，不写死 —— 加了迁移这里会自动跟上，
    # 而写死的表名只会静默产出一份空清单。
    {
        echo "# 备份时各表行数 ${STAMP}"
        sqlite3 "${BACKUP_DIR}/poster.db" \
            "SELECT name FROM sqlite_master WHERE type='table'
               AND name NOT LIKE 'sqlite_%' ORDER BY name;" \
        | while read -r table; do
            count="$(sqlite3 "${BACKUP_DIR}/poster.db" \
                "SELECT COUNT(*) FROM \"${table}\";")"
            printf '%-24s %s\n' "${table}" "${count}"
        done
    } > "${BACKUP_DIR}/db-rowcounts.txt" 2>/dev/null || true

    echo "    $(du -h "${BACKUP_DIR}/poster.db" | cut -f1) (源库 $(du -h "${DB_PATH}" | cut -f1) + WAL)"
else
    echo "!!! 找不到数据库 ${DB_PATH}" >&2
fi

# -------------------------------------------------------------------- 2. .env

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    cp "${PROJECT_ROOT}/.env" "${BACKUP_DIR}/env.backup"
    chmod 600 "${BACKUP_DIR}/env.backup"
    echo "==> .env 已备份（0600；含本地 VLM key，不要提交进仓库）"
fi

# ---------------------------------------------------------------- 3. 权重清单

echo "==> 权重清单"
{
    echo "# StagePoster 模型权重清单 ${STAMP}"
    echo "#"
    echo "# 重新下载见 scripts/download-models.sh。务必带 HF_HUB_DISABLE_XET=1，"
    echo "# 否则 Xet 大文件会绕过 hf-mirror 直连 cas-server.xethub.hf.co 并 401，"
    echo "# 目录看着是好的但权重是残的。下完按本表核对字节数。"
    echo "#"
    printf '%-14s %s\n' "BYTES" "PATH"
} > "${BACKUP_DIR}/model-manifest.txt"

cd "${PROJECT_ROOT}"
find models ComfyUI/models -type f \
    \( -name '*.safetensors' -o -name '*.pth' -o -name '*.bin' -o -name '*.onnx' \) \
    -printf '%s\t%p\n' 2>/dev/null \
    | sort -k2 \
    | while IFS=$'\t' read -r size path; do
        printf '%-14s %s\n' "${size}" "${path}"
    done >> "${BACKUP_DIR}/model-manifest.txt"

if [[ "${WITH_HASH}" == "1" ]]; then
    echo "    计算 sha256（43G，请等）"
    find models ComfyUI/models -type f \
        \( -name '*.safetensors' -o -name '*.pth' -o -name '*.bin' -o -name '*.onnx' \) \
        -print0 2>/dev/null \
        | sort -z \
        | xargs -0 sha256sum > "${BACKUP_DIR}/model-sha256.txt"
    echo "    -> model-sha256.txt"
fi

# -------------------------------------------------------------- 4. 代码状态

echo "==> 代码状态"
{
    echo "commit:  $(git rev-parse HEAD)"
    echo "branch:  $(git rev-parse --abbrev-ref HEAD)"
    echo "remote:  $(git remote get-url origin 2>/dev/null || echo '<none>')"
    echo "pushed:  $(test -z "$(git log --oneline @{u}..HEAD 2>/dev/null)" && echo yes || echo 'NO — 有未推送提交')"
    echo "clean:   $(test -z "$(git status --porcelain)" && echo yes || echo 'NO — 有未提交改动')"
    echo
    echo "--- 最近提交 ---"
    git log --oneline -10
} > "${BACKUP_DIR}/git-state.txt"
cat "${BACKUP_DIR}/git-state.txt" | head -5

# ------------------------------------------------------------- 5. 恢复说明

cat > "${BACKUP_DIR}/RESTORE.md" <<'RESTORE_EOF'
# 恢复步骤

这份备份**不含代码，也不含模型权重**。代码在 GitHub，权重靠重新下载。
这里只有那些既不在仓库、也无法自动重建的东西。

## 1. 代码

```bash
git clone git@github.com:Ripped-sys/StagePoster.git /workspace/poster-engine
cd /workspace/poster-engine
git checkout <git-state.txt 里的 commit>
```

## 2. 配置

```bash
cp env.backup /workspace/poster-engine/.env
```

`.env` 被 gitignore 排除，所以这是唯一副本。里面的 `DB_PATH` /
`STORAGE_ROOT` / `ASSET_STORAGE_ROOT` / `POSTER_OUTPUT_ROOT` 都指向
`/workspace/persistence/stageposter/...`；换了持久化根目录要一起改。

`REFERENCE_CONTROL_PATCH` 决定参考图条件化是否可用。它为空时后端照样启动，
只是参考图退化成"只影响需求理解那次 VLM 调用" —— 不会报错，容易被漏掉。

## 3. 数据库

```bash
# 停后端，避免写入竞争
cp poster.db /workspace/persistence/stageposter/data/poster.db
rm -f /workspace/persistence/stageposter/data/poster.db-wal \
      /workspace/persistence/stageposter/data/poster.db-shm
```

`poster.db` 是 `VACUUM INTO` 快照，WAL 已并入。**必须删掉旧的 -wal / -shm**，
否则 SQLite 会拿陈旧的 WAL 去套新库。

注意仓库里还有个 `backend/data/poster.db`，那是早期遗留，不是线上库。别恢复错。

## 4. 模型权重（约 43G）

```bash
bash scripts/download-models.sh
```

huggingface.co 直连不通，脚本走 hf-mirror。**必须带 `HF_HUB_DISABLE_XET=1`**，
否则 Xet 支撑的大文件绕过镜像直连 `cas-server.xethub.hf.co` 然后 401 ——
小文件下来了、权重没下来，目录看着像是好的。下完按 `model-manifest.txt`
逐个核对字节数，别只看退出码。

## 5. 产出物 storage/

`storage/`（候选图、成品海报、素材）本来就在持久化目录里，没有额外副本。
如果整个 `/workspace/persistence` 都没了，历史海报就没了 —— 数据库里的记录会
指向不存在的文件。这是已知的、被接受的风险：成品可以重新生成。

## 6. 起服务并验收

```bash
./scripts/start-all.sh
python3 scripts/e2e-test.py all      # 30 条路由，127 条断言
```

`start-all.sh` 会 `set -a; source .env`。**直接跑 `./poster-backend` 不读 .env**，
配置会静默丢失。
RESTORE_EOF

echo "==> RESTORE.md 已写入"

# 一个指向最新备份的稳定路径，恢复时不用去猜时间戳
ln -sfn "${BACKUP_DIR}" "${PERSIST_ROOT}/backups/latest"

echo
echo "==> 完成： ${BACKUP_DIR}"
ls -lh "${BACKUP_DIR}"
echo
echo "    latest -> $(readlink "${PERSIST_ROOT}/backups/latest")"
