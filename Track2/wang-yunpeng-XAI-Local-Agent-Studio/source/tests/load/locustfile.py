"""XAI 系统压测 — 5 个场景 + headless 报告输出。

使用:
    cd tests/load
    locust -f locustfile.py --headless -u 50 -r 10 -t 60s --html=../../docs/load_report.html
"""

from locust import HttpUser, task, between
import time


class XaiUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        r = self.client.get("/api/auth/token")
        self.token = r.json()["token"]
        self.headers = {"X-Auth-Token": self.token}

    @task(20)
    def health_check(self):
        """GET /api/system/health — 高频"""
        self.client.get("/api/system/health", headers=self.headers)

    @task(10)
    def memory_stats(self):
        """GET /api/memory/stats — 中频"""
        self.client.get("/api/memory/stats", headers=self.headers)

    @task(5)
    def chat_completion(self):
        """POST /api/chat/send — 对话"""
        self.client.post(
            "/api/chat/send",
            json={"text": "Hello world", "session_id": "load-test"},
            headers=self.headers,
        )

    @task(5)
    def memory_context(self):
        """GET /api/memory/context — 记忆召回"""
        self.client.get("/api/memory/context?text=test", headers=self.headers)

    @task(5)
    def system_errors(self):
        """GET /api/system/errors — 错误面板"""
        self.client.get("/api/system/errors?limit=20", headers=self.headers)
