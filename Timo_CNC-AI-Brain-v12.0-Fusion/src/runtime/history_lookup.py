"""
历史订单查询 Skill — 从 SQLite/JSON 读取客户历史数据。
为 BI 分析师提供硬数据支撑（而非 LLM 猜测）。
"""
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime


class HistoryLookup:
    """查询历史订单数据。"""

    DB_PATH = None

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path(__file__).resolve().parent.parent.parent / "data" / "orders.db")
        HistoryLookup.DB_PATH = db_path
        self._init_db()

    def _init_db(self):
        Path(HistoryLookup.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(HistoryLookup.DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE NOT NULL,
                    customer_name TEXT NOT NULL,
                    part_name TEXT NOT NULL,
                    material TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    final_price REAL NOT NULL,
                    surface_treatment TEXT DEFAULT '',
                    tolerance TEXT DEFAULT '',
                    status TEXT DEFAULT 'completed',
                    profit_rate REAL DEFAULT 0.25,
                    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_orders_material ON orders(material)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_name)
            """)
            conn.commit()

    def lookup(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        查询历史订单。
        
        Args:
            params: {material, customer_name, part_name, limit}
        
        Returns:
            标准 JSON: {total, records, stats}
        """
        material = params.get("material", "")
        customer = params.get("customer_name", "")
        part = params.get("part_name", "")
        limit = int(params.get("limit", 10))

        query = "SELECT * FROM orders WHERE 1=1"
        qparams = []

        if material:
            query += " AND material LIKE ?"
            qparams.append(f"%{material}%")
        if customer:
            query += " AND customer_name LIKE ?"
            qparams.append(f"%{customer}%")
        if part:
            query += " AND part_name LIKE ?"
            qparams.append(f"%{part}%")

        query += " ORDER BY created_at DESC LIMIT ?"
        qparams.append(limit)

        with sqlite3.connect(HistoryLookup.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, qparams).fetchall()

        records = [dict(r) for r in rows]

        # 统计
        stats = {}
        if records:
            prices = [r["final_price"] for r in records]
            stats = {
                "avg_price": round(sum(prices) / len(prices), 2),
                "min_price": min(prices),
                "max_price": max(prices),
                "avg_quantity": round(sum(r["quantity"] for r in records) / len(records), 0),
                "total_orders": len(records),
            }

        return {
            "total": len(records),
            "records": records,
            "stats": stats,
            "source": "SQLite orders.db",
        }

    def add_order(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """添加一条历史订单记录。"""
        order_id = params.get("order_id", f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        try:
            with sqlite3.connect(HistoryLookup.DB_PATH) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO orders
                    (order_id, customer_name, part_name, material, quantity, final_price,
                     surface_treatment, tolerance, status, profit_rate)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order_id,
                    params.get("customer_name", "未知客户"),
                    params.get("part_name", "未知零件"),
                    params.get("material", "未知材料"),
                    int(params.get("quantity", 1)),
                    float(params.get("final_price", 0)),
                    params.get("surface_treatment", ""),
                    params.get("tolerance", ""),
                    params.get("status", "completed"),
                    float(params.get("profit_rate", 0.25)),
                ))
                conn.commit()
            return {"success": True, "order_id": order_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def seed_demo_data(self):
        """预置演示数据。"""
        demo = [
            {"order_id": "ORD-20260501-001", "customer_name": "深圳智造科技", "part_name": "6061法兰", "material": "6061-T6", "quantity": 100, "final_price": 12300, "surface_treatment": "阳极氧化本色"},
            {"order_id": "ORD-20260503-002", "customer_name": "上海精密仪器", "part_name": "304轴套", "material": "304不锈钢", "quantity": 50, "final_price": 8900, "surface_treatment": "钝化", "tolerance": "IT7"},
            {"order_id": "ORD-20260505-003", "customer_name": "深圳智造科技", "part_name": "7075盖板", "material": "7075铝合金", "quantity": 200, "final_price": 18500, "surface_treatment": "阳极氧化黑色"},
            {"order_id": "ORD-20260508-004", "customer_name": "北京航发", "part_name": "钛合金叶轮", "material": "钛合金TC4", "quantity": 10, "final_price": 42000, "surface_treatment": "微弧氧化", "tolerance": "IT5"},
            {"order_id": "ORD-20260510-005", "customer_name": "广州机械", "part_name": "45钢齿轮", "material": "45钢", "quantity": 30, "final_price": 5600, "surface_treatment": "发黑"},
            {"order_id": "ORD-20260512-006", "customer_name": "上海精密仪器", "part_name": "316L接头", "material": "316L不锈钢", "quantity": 80, "final_price": 15600, "surface_treatment": "电解抛光", "tolerance": "IT6"},
            {"order_id": "ORD-20260514-007", "customer_name": "深圳智造科技", "part_name": "6061法兰", "material": "6061-T6", "quantity": 50, "final_price": 7656, "surface_treatment": "阳极氧化本色"},
        ]
        for d in demo:
            self.add_order(d)
        return {"seeded": len(demo)}

    def get_report(self) -> str:
        return json.dumps(self.lookup({"limit": 100}), ensure_ascii=False, indent=2)
