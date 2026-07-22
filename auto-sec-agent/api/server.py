"""AutoSec REST API Server — Flask-based web interface"""
import sys, os, json, threading, webbrowser
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from flask import Flask, jsonify, request, send_from_directory
except ImportError:
    print("Install Flask: pip install flask")
    sys.exit(1)

from agents.orchestrator import Orchestrator
from db.database import Database

app = Flask(__name__, static_folder=str(Path(__file__).parent.parent / "web"))
orch = Orchestrator()
db = Database()

# ─── API ENDPOINTS ───────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/stats")
def api_stats():
    return jsonify(db.get_stats())

@app.route("/api/targets")
def api_targets():
    return jsonify(db.get_targets())

@app.route("/api/agents")
def api_agents():
    return jsonify(db.get_agents())

@app.route("/api/scan", methods=["POST"])
def api_scan():
    data = request.json
    target = data.get("target", "").strip()
    use_rocm = data.get("rocm", False)
    if not target:
        return jsonify({"error": "No target provided"}), 400
    
    def run_scan():
        with app.app_context():
            result = orch.scan_target_full(target, use_rocm=use_rocm)
            # Store result for polling
    
    thread = threading.Thread(target=run_scan, daemon=True)
    thread.start()
    
    return jsonify({"status": "started", "target": target, "message": "Scan initiated"})

@app.route("/api/scans")
def api_scans():
    return jsonify(db.get_stats().get("recent_scans", []))

@app.route("/api/log")
def api_log():
    log_file = Path(__file__).parent.parent / "logs" / "autosec.log"
    if log_file.exists():
        with open(log_file) as f:
            lines = f.readlines()
        return jsonify({"logs": "".join(lines[-200:])})
    return jsonify({"logs": "No logs yet"})

def start_server(host="0.0.0.0", port=8080, open_browser=True):
    print(f"\n{G}[+] AutoSec Web Dashboard: http://{host}:{port}{N}")
    if open_browser:
        try:
            webbrowser.open(f"http://localhost:{port}")
        except:
            pass
    app.run(host=host, port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    start_server()
