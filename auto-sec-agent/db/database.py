"""
AutoSec Platform — Persistent Database Layer
SQLite-based storage for targets, scans, vulnerabilities, and users
"""
import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "autosec.db"

class Database:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path or DB_PATH)
        self._init_db()
    
    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    
    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT UNIQUE NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_scanned TIMESTAMP,
                status TEXT DEFAULT 'pending'
            );
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id INTEGER REFERENCES targets(id),
                scan_type TEXT NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                status TEXT DEFAULT 'running',
                subdomains_found INTEGER DEFAULT 0,
                vulnerabilities_found INTEGER DEFAULT 0,
                risk_score REAL DEFAULT 0,
                risk_level TEXT DEFAULT 'LOW',
                duration_seconds REAL DEFAULT 0,
                raw_results TEXT,
                FOREIGN KEY (target_id) REFERENCES targets(id)
            );
            CREATE TABLE IF NOT EXISTS vulnerabilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER REFERENCES scans(id),
                target_id INTEGER REFERENCES targets(id),
                name TEXT,
                severity TEXT,
                url TEXT,
                description TEXT,
                remediation TEXT,
                found_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (scan_id) REFERENCES scans(id),
                FOREIGN KEY (target_id) REFERENCES targets(id)
            );
            CREATE TABLE IF NOT EXISTS subdomains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER REFERENCES scans(id),
                target_id INTEGER REFERENCES targets(id),
                domain TEXT NOT NULL,
                ip_address TEXT,
                status_code INTEGER,
                found_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (scan_id) REFERENCES scans(id),
                FOREIGN KEY (target_id) REFERENCES targets(id)
            );
            CREATE TABLE IF NOT EXISTS agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                agent_type TEXT NOT NULL,
                status TEXT DEFAULT 'idle',
                last_active TIMESTAMP,
                config TEXT
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER REFERENCES agents(id),
                target_id INTEGER REFERENCES targets(id),
                task_type TEXT NOT NULL,
                status TEXT DEFAULT 'queued',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                result TEXT,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id INTEGER REFERENCES targets(id),
                scan_id INTEGER REFERENCES scans(id),
                format TEXT DEFAULT 'markdown',
                content TEXT,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                delivered_via TEXT
            );
        """)
        conn.commit()
        conn.close()
    
    # ─── TARGETS ──────────────────────────────────────────
    def add_target(self, domain):
        conn = self._get_conn()
        try:
            conn.execute("INSERT OR IGNORE INTO targets (domain) VALUES (?)", (domain,))
            conn.commit()
            cur = conn.execute("SELECT id FROM targets WHERE domain = ?", (domain,))
            return cur.fetchone()["id"]
        finally:
            conn.close()
    
    def get_targets(self, limit=50):
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM targets ORDER BY added_at DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    # ─── SCANS ────────────────────────────────────────────
    def start_scan(self, target_id, scan_type):
        conn = self._get_conn()
        conn.execute("INSERT INTO scans (target_id, scan_type) VALUES (?, ?)", (target_id, scan_type))
        conn.execute("UPDATE targets SET status = 'scanning', last_scanned = CURRENT_TIMESTAMP WHERE id = ?", (target_id,))
        conn.commit()
        scan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return scan_id
    
    def complete_scan(self, scan_id, subdomains, vulns, risk_score, risk_level, duration, raw=None):
        conn = self._get_conn()
        conn.execute("""
            UPDATE scans SET status='completed', completed_at=CURRENT_TIMESTAMP,
                subdomains_found=?, vulnerabilities_found=?, risk_score=?, 
                risk_level=?, duration_seconds=?, raw_results=?
            WHERE id=?
        """, (len(subdomains), len(vulns), risk_score, risk_level, duration, json.dumps(raw) if raw else None, scan_id))
        
        row = conn.execute("SELECT target_id FROM scans WHERE id = ?", (scan_id,)).fetchone()
        if row:
            conn.execute("UPDATE targets SET status='scanned' WHERE id=?", (row["target_id"],))
        
        # Store subdomains
        for sub in subdomains[:200]:
            conn.execute("INSERT INTO subdomains (scan_id, target_id, domain) VALUES (?, ?, ?)",
                        (scan_id, row["target_id"], sub))
        
        # Store vulnerabilities
        for v in vulns[:50]:
            info = v.get("info", {})
            conn.execute("""
                INSERT INTO vulnerabilities (scan_id, target_id, name, severity, url, description) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, (scan_id, row["target_id"], info.get("name", "Unknown"), 
                  info.get("severity", "info"), info.get("host", ""), info.get("description", "")))
        
        conn.commit()
        conn.close()
    
    # ─── STATS ────────────────────────────────────────────
    def get_stats(self):
        conn = self._get_conn()
        stats = {}
        stats["total_targets"] = conn.execute("SELECT COUNT(*) FROM targets").fetchone()[0]
        stats["total_scans"] = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
        stats["total_vulns"] = conn.execute("SELECT COUNT(*) FROM vulnerabilities").fetchone()[0]
        stats["total_subdomains"] = conn.execute("SELECT COUNT(*) FROM subdomains").fetchone()[0]
        stats["recent_scans"] = [
            dict(r) for r in conn.execute("""
                SELECT s.*, t.domain FROM scans s 
                JOIN targets t ON s.target_id = t.id 
                ORDER BY s.started_at DESC LIMIT 10
            """).fetchall()
        ]
        conn.close()
        return stats
    
    # ─── AGENTS ───────────────────────────────────────────
    def register_agent(self, name, agent_type, config=None):
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO agents (name, agent_type, config)
            VALUES (?, ?, ?)
        """, (name, agent_type, json.dumps(config) if config else "{}"))
        conn.commit()
        conn.close()
    
    def get_agents(self):
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM agents ORDER BY last_active DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
