import urllib.request
import json

BASE_URL = "https://khalilah-piteous-cortez.ngrok-free.dev"
HEADERS = {
    "Content-Type": "application/json",
    "ngrok-skip-browser-warning": "true"
}

def test_endpoint(name, path, method="GET", body=None):
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = resp.getcode()
            res_json = json.loads(resp.read().decode("utf-8"))
            print(f"[SUCCESS] [{name}] HTTP {code}")
            print(json.dumps(res_json, indent=2))
            return True
    except Exception as e:
        print(f"[ERROR] [{name}] Error: {e}")
        return False


if __name__ == "__main__":
    print("--- TESTING BACKEND ENDPOINTS OVER NGROK ---")
    test_endpoint("Health Check", "/health")
    test_endpoint("Tutor Agent", "/agent/tutor", "POST", {
        "child_id": "test_child",
        "session_id": "sess_123",
        "lesson_id": "lesson_1",
        "objective": "Move 10 steps",
        "workspace_blocks": ["s_when_flag"],
        "user_message": "What block comes next?"
    })
    test_endpoint("Grader Agent", "/agent/grade", "POST", {
        "child_id": "test_child",
        "lesson_id": "lesson_1",
        "workspace_xml": "<xml><block type=\"s_when_flag\"><next><block type=\"s_move\"></block></next></block></xml>",
        "helped_block_types": ["s_move"],
        "time_seconds": 45
    })
    test_endpoint("Curriculum Agent", "/agent/curriculum", "POST", {
        "child_id": "test_child",
        "completed_lessons": [],
        "weak_block_types": ["s_move"],
        "strong_block_types": ["s_when_flag"],
        "current_level": "Bronze",
        "total_xp": 100
    })
    test_endpoint("Benchmark Run", "/benchmark/run", "POST", {
        "prompt": "Explain loops simply",
        "use_local": True
    })
