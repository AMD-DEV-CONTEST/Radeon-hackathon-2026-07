#!/bin/bash
# 发布打包: 生成 GitHub Release ZIP + 校验
set -e

VERSION=$(grep 'version' pyproject.toml 2>/dev/null | head -1 | cut -d'"' -f2 || echo "11.0.2")
RELEASE="union_cnc_brain_v${VERSION}"
TMPDIR="/tmp/${RELEASE}"
ZIPFILE="${RELEASE}.tar.gz"

echo "========== Union CNC Brain 发布打包 v${VERSION} =========="

# 清理
rm -rf "$TMPDIR" "$ZIPFILE" 2>/dev/null
mkdir -p "$TMPDIR"

# 复制文件 (排除开发文件)
echo "[1/4] 复制项目文件..."
cd "$(dirname "$0")/.."
git archive --format=tar HEAD | tar x -C "$TMPDIR"

# 补充非git跟踪但需要的文件
for f in data models build dist; do
    [ -d "$f" ] && mkdir -p "$TMPDIR/$f"
done

# 移除 .git 等
rm -rf "$TMPDIR/.git" "$TMPDIR/__pycache__" "$TMPDIR/*/__pycache__" 2>/dev/null

# 加版本文件
echo "v${VERSION}" > "$TMPDIR/VERSION"

echo "  文件数: $(find "$TMPDIR" -type f | wc -l)"

# EXE 构建
echo "[2/4] 构建 Linux EXE..."
if command -v pyinstaller &>/dev/null && [ -f "$TMPDIR/union_by_ni.spec" ]; then
    cd "$TMPDIR"
    pyinstaller --clean --noconfirm union_by_ni.spec 2>/dev/null || echo "  (EXE构建跳过: 可能需要完整依赖)"
    if [ -f dist/union_cnc_brain ]; then
        cp dist/union_cnc_brain "$TMPDIR/"
        echo "  EXE: $(du -h "$TMPDIR/union_cnc_brain" | cut -f1)"
    fi
    cd - >/dev/null
else
    echo "  (跳过: pyinstaller 未安装)"
fi

# 打包
echo "[3/4] 打包 tar.gz..."
cd /tmp
tar czf "${RELEASE}.tar.gz" "${RELEASE}/"
SIZE=$(du -h "${RELEASE}.tar.gz" | cut -f1)
echo "  大小: $SIZE"

# 校验
echo "[4/4] 校验..."
MD5=$(md5sum "${RELEASE}.tar.gz" | cut -d' ' -f1)
SHA=$(sha256sum "${RELEASE}.tar.gz" | cut -d' ' -f1)
echo "  MD5: $MD5"
echo "  SHA256: $SHA"

# 校验文件写入
echo "v${VERSION} | $(date -I) | MD5=${MD5} | SHA256=${SHA} | Size=${SIZE}" > "${RELEASE}.checksum.txt"

echo ""
echo "========== 发布包就绪 =========="
echo "  文件: /tmp/${RELEASE}.tar.gz"
echo "  大小: $SIZE"
echo "  MD5:  $MD5"
