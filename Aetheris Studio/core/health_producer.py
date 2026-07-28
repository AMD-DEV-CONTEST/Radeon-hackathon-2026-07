import time
import threading
import httpx
from datetime import datetime, timezone
from core.event_bus import bus
from core.memory.chat_history import get_db

class HealthProducer:
    def __init__(self, interval_seconds=15):
        self.interval_seconds = interval_seconds
        self.running = False
        self.ollama_url = "http://127.0.0.1:11434"
        
        # Last known states to prevent spamming exactly same statuses
        self.last_ollama = None
        self.last_sqlite = None
        
    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._run_loop, daemon=True).start()
            
    def stop(self):
        self.running = False
        
    def _run_loop(self):
        # Ollama removido (VTE é o motor): o loop de health checa só o
        # SQLite. Antes também pollava http://127.0.0.1:11434 (Ollama, sempre
        # offline aqui) e rodava rocm-smi a cada ciclo -- ambos removidos.
        while self.running:
            self.check_and_publish_sqlite()
            time.sleep(self.interval_seconds)

    def check_and_publish_sqlite(self):
        """Episodic chat history moved from MongoDB to the local SQLite
        store (core/memory/chat_history.py) -- this checks that, not Mongo."""
        try:
            db = get_db()
            status = "ok" if db is not None else "error"
        except Exception:
            status = "error"

        if status != self.last_sqlite:
            self.last_sqlite = status
            bus.publish("aetheris.status.sqlite", {"service": "sqlite", "status": status, "ts": datetime.now(timezone.utc).isoformat()})

# Singleton producer
producer = HealthProducer(interval_seconds=15)

def start_health_checks():
    producer.start()
