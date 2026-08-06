#!/usr/bin/env python3
"""
清洗 state.db 会话数据 → 去除 cron 噪音 → 分块摄入 RAG
"""
import sqlite3
import json
import re
import sys
import urllib.request
from datetime import datetime

STATE_DB = "/root/.hermes/state.db"
RAG_URL = "http://127.0.0.1:8010/documents/ingest"
MAX_CHUNK_SIZE = 1800    # embed_text 截断 2000，留 buffer
BATCH_SIZE = 50          # RAG /documents/ingest 限制

# ── 噪音过滤器 ──────────────────────────────────────────────

NOISE_PATTERNS = [
    r'health_check',
    r'\[SILENT\]',
    r'mem_MCP.*健康检查',
    r'IMPORTANT: You are running as a scheduled cron job',
    r'执行 /root/.hermes/scripts/health_check\.sh',
    r'Log file not found or empty',
    r'mem_MCP 健康检查报告',
    r'历史趋势.*最近.*次检查.*全部通过',
    r'MCP 端口.*正常',
    r'PostgreSQL.*正常',
    r'TCP 连接成功',
    r'服务已持续运行',
    r'健康检查报告.*✅',
    r'\| 检查项 \| 状态 \| 详情 \|',
    r'\| MCP 服务.*端口.*\| ✅',
    r'\| PostgreSQL.*\| ✅',
    r'\| Git 仓库.*\| ✅',
    r'\| /health 端点.*\| ✅',
    r'健康端点.*✅.*healthy',
    r'cron job.*DELIVERY',
    r'DELIVERY: Your final response',
    r'状态：全部正常 ✅',
    r'\| 检查项 \| 状态 \| 详情 \|',
    r'\| MCP 端口 3000 \| ✅',
]

def is_noise(content: str) -> bool:
    """判断消息是否为噪音"""
    if not content or len(content.strip()) < 5:
        return True  # 空消息或极短消息
    for pat in NOISE_PATTERNS:
        if re.search(pat, content, re.IGNORECASE):
            return True
    return False


def chunk_text(text: str, max_size: int = MAX_CHUNK_SIZE) -> list[str]:
    """将长文本按段落分块"""
    if len(text) <= max_size:
        return [text]
    
    chunks = []
    paragraphs = text.split('\n\n')
    current = ""
    
    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_size:
            current = (current + '\n\n' + para).strip()
        else:
            if current:
                chunks.append(current)
            if len(para) > max_size:
                # 超长段落按句子切
                sentences = re.split(r'(?<=[。.!！?？\n])', para)
                for s in sentences:
                    if len(current) + len(s) + 1 <= max_size:
                        current = (current + ' ' + s).strip()
                    else:
                        if current:
                            chunks.append(current)
                        current = s
            else:
                current = para
    
    if current:
        chunks.append(current)
    
    return [c for c in chunks if len(c.strip()) > 10]


def ingest_chunks(chunks: list[dict]) -> int:
    """发送批次到 RAG"""
    payload = json.dumps({"chunks": chunks}).encode()
    req = urllib.request.Request(
        RAG_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data.get("count", 0)
    except urllib.error.HTTPError as e:
        print(f"  RAG error: {e.code} {e.read().decode()[:200]}")
        return 0
    except Exception as e:
        print(f"  Network error: {e}")
        return 0


def main():
    db = sqlite3.connect(STATE_DB)
    db.row_factory = sqlite3.Row
    
    # 1. 取有效会话（排除 cron）
    valid_sessions = db.execute(
        "SELECT id, source, started_at, title FROM sessions WHERE source != 'cron' ORDER BY started_at"
    ).fetchall()
    
    print(f"有效会话: {len(valid_sessions)} 个")
    
    sys.stdout.reconfigure(line_buffering=True)  # Force flush every line
    
    total_chunks = 0
    batch = []
    session_count = 0
    
    for sess in valid_sessions:
        session_count += 1
        sid = sess["id"]
        source = sess["source"]
        title = sess["title"] or f"会话 {sid[:8]}"
        ts = datetime.fromtimestamp(sess["started_at"]).strftime("%Y-%m-%d %H:%M")
        
        # 2. 取该会话的所有真实消息
        rows = db.execute(
            "SELECT role, content, timestamp FROM messages WHERE session_id = ? AND role IN ('user', 'assistant') ORDER BY timestamp",
            (sid,)
        ).fetchall()
        
        # 3. 过滤噪音
        clean_msgs = []
        for row in rows:
            content = row["content"] or ""
            if not is_noise(content):
                clean_msgs.append(f"[{row['role']}]: {content}")
        
        if not clean_msgs:
            continue
        
        # 4. 构建对话文本
        full_text = f"会话: {title}\n来源: {source}\n时间: {ts}\n\n" + "\n".join(clean_msgs)
        
        # 5. 分块
        chunks = chunk_text(full_text)
        
        for i, ch in enumerate(chunks):
            batch.append({
                "source_type": "session",
                "source_id": f"{sid}-{i}",
                "chunk_index": i,
                "title": title[:200],
                "content": ch,
                "tags": [source, f"msgs:{len(clean_msgs)}"],
                "metadata": {
                    "session_id": sid,
                    "source": source,
                    "started_at": sess["started_at"],
                    "msg_count": len(clean_msgs),
                    "chunk_count": len(chunks),
                },
            })
            
            # 6. 批次满 50 发送
            if len(batch) >= BATCH_SIZE:
                n = ingest_chunks(batch)
                total_chunks += n
                print(f"  [{session_count}/{len(valid_sessions)}] 已摄入 {total_chunks} 分块 (批次 {n})")
                batch = []
    
    # 7. 发送剩余
    if batch:
        n = ingest_chunks(batch)
        total_chunks += n
        print(f"  [{session_count}/{len(valid_sessions)}] 最终批次: {n}, 总计: {total_chunks}")
    
    print(f"\n✅ 完成! {len(valid_sessions)} 会话 → {total_chunks} 分块 摄入 RAG")
    
    # 8. 统计
    stats_req = urllib.request.Request("http://127.0.0.1:8010/documents/stats")
    with urllib.request.urlopen(stats_req) as resp:
        stats = json.loads(resp.read())
    print(f"RAG 文档统计: {json.dumps(stats, ensure_ascii=False)}")
    
    db.close()


if __name__ == "__main__":
    main()
