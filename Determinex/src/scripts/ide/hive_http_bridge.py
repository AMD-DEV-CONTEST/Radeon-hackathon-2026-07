import http.server
import json
import os
import socketserver
import subprocess
import sys
import urllib.request

PORT = 7479
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def user_safe_process_error(action: str, stderr: str) -> str:
    cleaned = stderr.replace("\x1b", "")
    for line in cleaned.splitlines():
        if "USER_ERROR:" in line:
            return line.split("USER_ERROR:", 1)[1].strip()

    lower = cleaned.lower()
    if "ollama" in lower and "model" in lower and "not found" in lower:
        return (
            f"{action} could not continue because the selected Ollama model is not installed. "
            "Open Settings -> Models to repair local models, or pull the missing model in Ollama."
        )
    if "ollama" in lower and any(
        token in lower for token in ("connection", "refused", "unreachable")
    ):
        return f"{action} could not continue because Ollama is not reachable. Start Ollama, then retry."
    if "cloud model blocked" in lower or "determinex_allow_cloud_fallback" in lower:
        return (
            f"{action} tried to use a cloud model, but cloud fallback is disabled. "
            "Choose a local model in Settings -> Models or explicitly enable cloud fallback."
        )

    useful_lines = [
        line.strip()
        for line in cleaned.splitlines()
        if line.strip()
        and "LiteLLM" not in line
        and "botocore" not in line
        and "sagemaker" not in line.lower()
        and "bedrock" not in line.lower()
        and "[SAFETY]" not in line
    ]
    detail = useful_lines[-1] if useful_lines else "Check model setup and retry."
    return f"{action} failed. {detail}"


class HTTPBridgeHandler(http.server.SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "X-Requested-With, Content-type")
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-type", "application/json")
        self.end_headers()

        try:
            payload = json.loads(post_data) if post_data else {}
        except json.JSONDecodeError:
            self.wfile.write(json.dumps({"ok": False, "error": "Invalid JSON payload"}).encode())
            return

        path = self.path

        if path == "/api/invoke/check_ollama_status":
            try:
                req = urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
                if req.getcode() == 200:
                    self.wfile.write(json.dumps({"ok": True}).encode())
                else:
                    self.wfile.write(
                        json.dumps(
                            {"ok": False, "error": f"Ollama returned {req.getcode()}"}
                        ).encode()
                    )
            except Exception as e:
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
            return
        elif path == "/api/invoke/get_ollama_models":
            try:
                req = urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
                if req.getcode() == 200:
                    data = json.loads(req.read().decode())
                    models = []
                    for model in data.get("models", []):
                        size_gb = model.get("size", 0) / (1024**3)
                        models.append(
                            {
                                "id": model.get("name"),
                                "name": model.get("name"),
                                "size_gb": round(size_gb, 2),
                                "param_size": model.get("details", {}).get(
                                    "parameter_size", "Unknown"
                                ),
                                "is_determinex": "determinex" in model.get("name", "").lower(),
                            }
                        )
                    self.wfile.write(json.dumps(models).encode())
                else:
                    self.wfile.write(
                        json.dumps(
                            {"ok": False, "error": f"Ollama returned {req.getcode()}"}
                        ).encode()
                    )
            except Exception as e:
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
            return
        elif path == "/api/invoke/get_role_assignments":
            config_path = os.path.join(PROJECT_ROOT, "litellm_config.yaml")
            roles = {
                "oracle": "local/fast",
                "architect": "local/fast",
                "builder": "determinex/engineer",
                "monitor": "determinex/observer",
            }
            try:
                if os.path.exists(config_path):
                    import re

                    with open(config_path, encoding="utf-8") as handle:
                        config = handle.read()
                    for role in roles:
                        match = re.search(r"^\s+" + role + r":\s+(\S+)", config, re.MULTILINE)
                        if match:
                            roles[role] = match.group(1)
                self.wfile.write(json.dumps({"ok": True, "data": roles}).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
            return
        elif path == "/api/invoke/get_work_readiness":
            config_path = os.path.join(PROJECT_ROOT, "litellm_config.yaml")
            roles = {
                "oracle": "local/fast",
                "architect": "local/fast",
                "builder": "determinex/engineer",
                "monitor": "determinex/observer",
            }
            aliases = {}
            try:
                import re
                import time

                if os.path.exists(config_path):
                    with open(config_path, encoding="utf-8") as handle:
                        config = handle.read()
                    for match in re.finditer(
                        r"(?ms)^\s*-\s*model_name:\s*([^\s#]+)(.*?)(?=^\s*-\s*model_name:|^router_settings:|^determinex:|\Z)",
                        config,
                    ):
                        model_match = re.search(r"(?m)^\s*model:\s*([^\s#]+)", match.group(2))
                        if model_match:
                            aliases[match.group(1)] = model_match.group(1)
                    for role in roles:
                        match = re.search(r"^\s+" + role + r":\s+(\S+)", config, re.MULTILINE)
                        if match:
                            roles[role] = match.group(1)

                try:
                    req = urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
                    ollama_ok = req.getcode() == 200
                    tags = json.loads(req.read().decode()) if ollama_ok else {"models": []}
                except Exception:
                    self.wfile.write(
                        json.dumps(
                            {
                                "status": "offline",
                                "ready": False,
                                "label": "Ollama Offline",
                                "summary": "Ollama is not reachable. Start Ollama before generating specs.",
                                "details": [],
                                "missingRoles": list(roles.keys()),
                                "checkedAt": int(time.time() * 1000),
                            }
                        ).encode()
                    )
                    return

                def normalize(value):
                    value = value.strip()
                    if value.startswith("ollama/"):
                        value = value[len("ollama/") :]
                    if value.endswith(":latest"):
                        value = value[: -len(":latest")]
                    return value.lower()

                def is_cloud(value):
                    return value.startswith(
                        ("cloud/", "openai/", "anthropic/", "gemini/", "deepseek/")
                    )

                installed = {
                    normalize(model.get("name", ""))
                    for model in tags.get("models", [])
                    if model.get("name")
                }
                checks = []
                details = []
                missing = []
                cloud = []
                for role, assignment in roles.items():
                    target = aliases.get(assignment)
                    if not target and (assignment.startswith("ollama/") or "/" not in assignment):
                        target = assignment
                    if is_cloud(assignment):
                        message = f"{role} uses {assignment}"
                        cloud.append(message)
                        checks.append(
                            {
                                "role": role,
                                "assignment": assignment,
                                "target_model": target,
                                "status": "cloud",
                                "message": message,
                            }
                        )
                        continue
                    if target and normalize(target) in installed:
                        message = f"{role} -> {target}"
                        details.append(message)
                        checks.append(
                            {
                                "role": role,
                                "assignment": assignment,
                                "target_model": target,
                                "status": "ready",
                                "message": message,
                            }
                        )
                    elif target:
                        message = f"{role} needs {target.replace('ollama/', '')}"
                        missing.append(message)
                        checks.append(
                            {
                                "role": role,
                                "assignment": assignment,
                                "target_model": target,
                                "status": "missing",
                                "message": message,
                            }
                        )
                    else:
                        message = f"{role} has unresolved assignment {assignment}"
                        missing.append(message)
                        checks.append(
                            {
                                "role": role,
                                "assignment": assignment,
                                "target_model": None,
                                "status": "unknown",
                                "message": message,
                            }
                        )

                if missing:
                    payload = {
                        "status": "attention",
                        "ready": False,
                        "label": "Attention",
                        "summary": f"Missing local model coverage for {len(missing)} role{'s' if len(missing) != 1 else ''}.",
                        "details": missing,
                        "missingRoles": missing,
                        "checks": checks,
                        "checkedAt": int(time.time() * 1000),
                    }
                elif cloud:
                    payload = {
                        "status": "attention",
                        "ready": False,
                        "label": "Cloud Selected",
                        "summary": "One or more Hive roles use cloud models. Confirm API keys or switch to local roles before generating.",
                        "details": cloud,
                        "missingRoles": cloud,
                        "checks": checks,
                        "checkedAt": int(time.time() * 1000),
                    }
                else:
                    payload = {
                        "status": "ready",
                        "ready": True,
                        "label": "Model Ready",
                        "summary": "All local Hive roles resolve to installed Ollama models.",
                        "details": details,
                        "missingRoles": [],
                        "checks": checks,
                        "checkedAt": int(time.time() * 1000),
                    }
                self.wfile.write(json.dumps(payload).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
            return

        elif path == "/api/invoke/discover_idea":
            script = os.path.join(PROJECT_ROOT, "scripts", "idea_oracle.py")
            cmd = [sys.executable, script, "--mode", "discover"]
            stdin_data = json.dumps(payload.get("payload", {}))
            is_json_output = True

        elif path == "/api/invoke/converse_idea":
            script = os.path.join(PROJECT_ROOT, "scripts", "idea_oracle.py")
            cmd = [sys.executable, script, "--mode", "converse"]
            stdin_data = json.dumps(payload.get("payload", {}))
            is_json_output = True

        elif path == "/api/invoke/provider_setup_report":
            # "Which button do I press?" -- what already works, and the ONE thing to do next.
            script = os.path.join(PROJECT_ROOT, "scripts", "determinex_provider_setup.py")
            cmd = [sys.executable, script, "report"]
            stdin_data = ""
            is_json_output = True

        elif path == "/api/invoke/provider_setup_verify":
            # A green check must mean a real call happened, so this makes one.
            script = os.path.join(PROJECT_ROOT, "scripts", "determinex_provider_setup.py")
            cmd = [sys.executable, script, "verify",
                   "--id", str((payload.get("payload") or {}).get("id", ""))]
            stdin_data = ""
            is_json_output = True

        elif path == "/api/invoke/user_profile_get":
            script = os.path.join(PROJECT_ROOT, "scripts", "determinex_user_profile.py")
            cmd = [sys.executable, script, "prescreen"]
            stdin_data = ""
            is_json_output = True

        elif path == "/api/invoke/user_profile_set":
            script = os.path.join(PROJECT_ROOT, "scripts", "determinex_user_profile.py")
            cmd = [sys.executable, script, "set",
                   "--level", str((payload.get("payload") or {}).get("level", ""))]
            stdin_data = ""
            is_json_output = True

        elif path == "/api/invoke/assess_idea_context":
            # "Do we know enough to build this yet?" -- answered by whether a SOUND ORACLE
            # can be synthesized from the accumulated answers, not by counting questions.
            # This is what lets the Concept Lab interview run past the old 4-question bank
            # instead of generating a spec from whatever it happened to have.
            script = os.path.join(PROJECT_ROOT, "scripts", "idea_context.py")
            cmd = [sys.executable, script, "--stdin"]
            stdin_data = json.dumps(payload.get("payload", {}))
            is_json_output = True

        elif path == "/api/invoke/generate_spec":
            script = os.path.join(PROJECT_ROOT, "scripts", "spec_generator.py")
            cmd = [sys.executable, script, "--stdin"]
            stdin_data = json.dumps({"idea": payload.get("payload", {}).get("idea", "")})
            is_json_output = False

        else:
            self.wfile.write(
                json.dumps({"ok": False, "error": f"Unknown endpoint {path}"}).encode()
            )
            return

        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=PROJECT_ROOT,
            )
            stdout, stderr = process.communicate(input=stdin_data.encode())
            if process.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="ignore")
                action = "Spec generation" if path.endswith("/generate_spec") else "Oracle"
                self.wfile.write(
                    json.dumps(
                        {"ok": False, "error": user_safe_process_error(action, err_msg)}
                    ).encode()
                )
                return

            stdout_str = stdout.decode("utf-8", errors="ignore").strip()

            if is_json_output:
                try:
                    # Strip any non-JSON lines before the first '{' (e.g. logging output)
                    if "{" in stdout_str:
                        stdout_str = stdout_str[stdout_str.find("{") :]
                    parsed = json.loads(stdout_str)
                    if "error" in parsed:
                        self.wfile.write(
                            json.dumps({"ok": False, "error": parsed["error"]}).encode()
                        )
                    else:
                        self.wfile.write(json.dumps({"ok": True, "data": parsed}).encode())
                except json.JSONDecodeError:
                    self.wfile.write(
                        json.dumps(
                            {"ok": False, "error": f"Failed to parse JSON: {stdout_str}"}
                        ).encode()
                    )
            else:
                self.wfile.write(json.dumps({"ok": True, "data": {"spec": stdout_str}}).encode())

        except Exception as e:
            self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())


class ReuseAddrServer(socketserver.TCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    with ReuseAddrServer(("", PORT), HTTPBridgeHandler) as httpd:
        print(f"Starting Determinex HTTP Bridge on port {PORT}")
        httpd.serve_forever()
