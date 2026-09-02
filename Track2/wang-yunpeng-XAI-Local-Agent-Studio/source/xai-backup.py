#!/usr/bin/env python3
"""
xai-backup.py — XAI 本地数据的在线原子备份 + 完整性校验 + 轮转。

设计原则（solo 本地部署）:
  - 用 sqlite3 连接对象的 backup() 做在线拷贝，绝不 `cp` 正在写入的 .db
    （直接拷活库会得到半写损坏文件，这是本地备份最常见也最致命的坑）。
  - 每份备份后跑 PRAGMA integrity_check。
  - 仅备份 SQLite 数据库 + 关键配置 JSON；明确排除 chrome-profile
    （浏览器自动化缓存，体积大且可重建）。
  - 保留最近 7 天，自动轮转。

用法:
  python3 xai-backup.py            # 立即备份
  python3 xai-backup.py --verify   # 备份后再做一次恢复演练（还原到临时目录并校验）
"""
import sqlite3
import os
import shutil
import datetime
import sys
import tempfile

XAI_HOME = os.path.expanduser(os.environ.get("XAI_HOME", "~/.xai"))
BACKUP_ROOT = os.path.join(XAI_HOME, "backups", "db")
KEEP_DAYS = 7
EXCLUDE_DIRS = {"chrome-profile", "backups"}
NOW = datetime.datetime.now()
TS = NOW.strftime("%Y%m%dT%H%M%S")


def find_db_files():
    results = []
    for root, dirs, files in os.walk(XAI_HOME):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]  # 剪枝，不进入排除目录
        for f in files:
            if f.endswith(".db"):
                results.append(os.path.join(root, f))
    return results


def backup_one(db_path):
    rel = os.path.relpath(db_path, XAI_HOME).replace("/", "__")
    dest = os.path.join(BACKUP_ROOT, f"{rel}.{TS}.bak")
    try:
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(dest)
        src.backup(dst)
        src.close()
        dst.close()
        c = sqlite3.connect(dest)
        rows = c.execute("PRAGMA integrity_check").fetchall()
        c.close()
        ok = all(r[0] == "ok" for r in rows)
        return {"rel": os.path.relpath(db_path, XAI_HOME), "ok": ok,
                "size": os.path.getsize(dest), "error": None}
    except Exception as e:
        return {"rel": os.path.relpath(db_path, XAI_HOME), "ok": False,
                "size": 0, "error": str(e)[:200]}


def backup_config_jsons():
    cfg_dir = os.path.join(BACKUP_ROOT, "config", TS)
    copied = []
    for f in os.listdir(XAI_HOME):
        fp = os.path.join(XAI_HOME, f)
        if f.endswith(".json") and os.path.isfile(fp):
            os.makedirs(cfg_dir, exist_ok=True)
            shutil.copy2(fp, os.path.join(cfg_dir, f))
            copied.append(f)
    return copied


def rotate():
    cutoff = NOW.timestamp() - KEEP_DAYS * 86400
    removed = 0
    for root, _, files in os.walk(BACKUP_ROOT):
        for f in files:
            fp = os.path.join(root, f)
            try:
                if os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
                    removed += 1
            except OSError:
                pass
    return removed


def verify_recovery():
    dbs = sorted(
        (os.path.join(BACKUP_ROOT, f) for f in os.listdir(BACKUP_ROOT)
         if f.endswith(".bak")),
        key=os.path.getmtime, reverse=True,
    )
    if not dbs:
        print("[verify] 无备份可演练")
        return False
    target = dbs[0]
    tmp = tempfile.mkdtemp(prefix="xai-restore-drill-")
    restored = os.path.join(tmp, "restored.db")
    try:
        src = sqlite3.connect(target)
        dst = sqlite3.connect(restored)
        src.backup(dst)
        src.close()
        dst.close()
        c = sqlite3.connect(restored)
        rows = c.execute("PRAGMA integrity_check").fetchall()
        c.close()
        ok = all(r[0] == "ok" for r in rows)
        print(f"[verify] 演练 {os.path.basename(target)} -> 还原 integrity={'OK' if ok else 'FAIL'}")
        return ok
    except Exception as e:
        print(f"[verify] 演练失败: {e}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    os.makedirs(BACKUP_ROOT, exist_ok=True)
    print(f"[xai-backup] XAI_HOME={XAI_HOME}  TS={TS}")
    dbs = find_db_files()
    print(f"[xai-backup] 发现 {len(dbs)} 个数据库文件")
    all_ok = True
    for db in dbs:
        r = backup_one(db)
        status = "OK" if r["ok"] else "FAIL"
        size = f"{r['size'] // 1024}KB" if r["size"] else "-"
        line = f"[{status}] {r['rel']} ({size})"
        if r["error"]:
            line += f" err={r['error']}"
        print("[xai-backup] " + line)
        all_ok = all_ok and r["ok"]
    cfgs = backup_config_jsons()
    if cfgs:
        print(f"[xai-backup] 配置JSON已备份: {', '.join(cfgs)}")
    removed = rotate()
    if removed:
        print(f"[xai-backup] 轮转清理 {removed} 个过期备份")
    if "--verify" in sys.argv:
        all_ok = verify_recovery() and all_ok
    print(f"[xai-backup] 完成 {'✅' if all_ok else '⚠️ 有失败项'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
