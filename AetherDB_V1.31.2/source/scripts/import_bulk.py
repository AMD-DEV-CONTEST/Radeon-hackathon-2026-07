#!/usr/bin/env python3
"""批量导入脚本 — 从 HTML/纯文本/Markdown 文件中提取段落并写入数据库。"""

import argparse, json, os, re, sqlite3, sys


ENTITY_TYPES = {
    "character": "人物", "faction": "阵营/组织", "location": "地点/场景",
    "rule": "规则/法则", "event": "事件", "item": "物品/道具",
    "concept": "概念/设定", "system": "系统/体系",
}
ENTITY_PREFIXES = {
    "character": "CHR", "faction": "FAC", "location": "LOC",
    "rule": "RUL", "event": "EVT", "item": "ITM",
    "concept": "CON", "system": "SYS",
}


def detect_type(title, content):
    text = (title + " " + content).lower()
    if any(k in text for k in ["人物","角色","主角","帝","修士","强者"]): return "character"
    if any(k in text for k in ["阵营","组织","国家","种族","宗门","联邦","联盟","战线"]): return "faction"
    if any(k in text for k in ["地点","场景","区域","大陆","城市","秘境","关卡","防线"]): return "location"
    if any(k in text for k in ["规则","法则","定律","秩序"]): return "rule"
    if any(k in text for k in ["事件","历史","战争","战役","时代"]): return "event"
    if any(k in text for k in ["物品","道具","神器","法宝","装备"]): return "item"
    if any(k in text for k in ["概念","理念","设定","本质"]): return "concept"
    if any(k in text for k in ["系统","体系","框架","境界","等级"]): return "system"
    return "concept"


def parse_sections(text):
    """将输入文本解析为段落列表。"""
    sections = []
    if "<" in text and ">" in text:
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</?p[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;"," ").replace("&amp;","&")
    text = text.replace("&lt;","<").replace("&gt;",">").replace("&quot;",'"')

    lines = text.split("\n")
    current_title = ""
    current_content = []

    for line in lines:
        s = line.strip()
        if not s or re.match(r"^-{3,}$", s) or re.match(r"^={3,}$", s):
            if current_title or current_content:
                sections.append({"title": current_title, "content": "\n".join(current_content).strip()})
                current_title = ""; current_content = []
            continue
        if re.match(r"^#{1,3}\s", s) or re.match(r"^第[一二三四五六七八九十百千]+[章节篇部]", s):
            # Save previous section
            if current_title or current_content:
                sections.append({"title": current_title, "content": "\n".join(current_content).strip()})
            current_title = s; current_content = []
            continue
        # Skip standalone "---" lines
        if s == "---": continue
        current_content.append(s)

    if current_title or current_content:
        sections.append({"title": current_title, "content": "\n".join(current_content).strip()})
    return [s for s in sections if len(s["content"]) > 5 or len(s["title"]) > 2]


def import_to_db(sections, db_path, dry_run=False):
    stats = {"entities": 0, "relations": 0, "errors": 0}
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()

        for section in sections:
            title = section["title"] or section["content"][:50]
            content = section["content"]
            etype = detect_type(title, content)
            importance = max(1, min(10, 5 + (1 if len(content) > 200 else 0) + (1 if len(content) > 500 else 0)))
            tags = list(set(re.findall(r"[\u4e00-\u9fff]{2,4}", title + content[:200])))[:5]

            if dry_run:
                print(f"  [DRY-RUN] {etype}: {title[:60]}")
                stats["entities"] += 1
                continue

            prefix = ENTITY_PREFIXES.get(etype, "GEN")
            cursor.execute("SELECT MAX(CAST(SUBSTR(entity_id,5) AS INTEGER)) FROM entities WHERE entity_id LIKE ?", (prefix+"_%",))
            max_id = cursor.fetchone()[0]
            entity_id = f"{prefix}_{(max_id or 0) + 1:04d}"

            tags_json = json.dumps(tags, ensure_ascii=False)
            sql = ("INSERT INTO entities (entity_id, entity_type, title, content, tags, importance, ai_summary) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?)")
            cursor.execute(sql, (entity_id, etype, title[:200], content[:5000], tags_json, importance, content[:500]))
            for tag in tags:
                cursor.execute("INSERT INTO tag_index (entity_id, tag) VALUES (?, ?)", (entity_id, tag.strip()))
            stats["entities"] += 1
            print(f"  [OK] {entity_id} {etype}: {title[:60]}")

        conn.commit()
    except Exception as e:
        stats["errors"] += 1
        print(f"  [ERROR] {e}", file=sys.stderr)
        if conn: conn.rollback()
    finally:
        if conn: conn.close()
    return stats


def main():
    parser = argparse.ArgumentParser(description="批量导入设定文本到世界观数据库")
    parser.add_argument("files", nargs="*", help="输入文件")
    parser.add_argument("--db-path", default="novel_world_zh.db", help="数据库路径")
    parser.add_argument("--dry-run", action="store_true", help="预览模式")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取")
    args = parser.parse_args()

    if not args.files and not args.stdin:
        parser.print_help(); sys.exit(1)

    total = {"entities": 0, "errors": 0}

    if args.stdin:
        text = sys.stdin.read()
        print(f"从标准输入读取: {len(text)} 字符")
        sections = parse_sections(text)
        print(f"解析到 {len(sections)} 个段落")
        stats = import_to_db(sections, args.db_path, args.dry_run)
        for k in total: total[k] += stats[k]

    for fp in args.files:
        if not os.path.exists(fp):
            print(f"文件不存在: {fp}", file=sys.stderr)
            total["errors"] += 1; continue
        with open(fp, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        print(f"\n=== {os.path.basename(fp)} ({len(text)} 字符) ===")
        sections = parse_sections(text)
        print(f"解析到 {len(sections)} 个段落")
        stats = import_to_db(sections, args.db_path, args.dry_run)
        for k in total: total[k] += stats[k]

    print(f"\n{'='*40}")
    print(f"{'预览' if args.dry_run else '导入'}完成: {total['entities']} 个实体, {total['errors']} 个错误")


if __name__ == "__main__":
    main()
