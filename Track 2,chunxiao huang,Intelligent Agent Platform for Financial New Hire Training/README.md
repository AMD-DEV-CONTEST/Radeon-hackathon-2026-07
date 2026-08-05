1 Place the source code package ai_knowledge_platform and attachment  FinancialBancassurance.mp4 under the /workspace directory
2. Create Python virtual environment
python3 -m venv venv_ms
Activate virtual environment
source venv_ms/bin/activate
3. ===== Install dependencies from requirements.txt ============
pip install -r ai_knowledge_platform/requirements.txt
4. ======== Download local LLM Qwen3-14B-AWQ =========
pip install modelscope
modelscope download --model JunHowie/Qwen3-14B-Instruct-2512-SFT-AWQ --local_dir ./persistent/Qwen3-14B-AWQ
5. ========== Install ROCm-version PyTorch for current environment ==========
pip uninstall torchvision
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm7.2
6. ========== Launch local LLM service ===
vllm serve /workspace/persistent/Qwen3-14B-AWQ
--host 0.0.0.0
--port 8000
--dtype float16
--gpu-memory-utilization 0.6
--max-model-len 16384
7. ========== Install MySQL ===
sudo apt install mysql-server -y
Start MySQL service
service mysql start
mysql -u root -p
CREATE DATABASE ai_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'rootroot';
FLUSH PRIVILEGES;
8. ========== Start MinerU service ===============
Set model source (domestic acceleration mirror)
export MINERU_MODEL_SOURCE=modelscope
Launch parsing API service
mineru-api --host 0.0.0.0 --port 8001
9. ============ Launch FastAPI backend ======= =======
cd ai_knowledge_platform
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --log-level debug
10. =========== Rebuild frontend dependencies ============
cd ai_knowledge_platform/frontend/
rm -rf node_modules package-lock.json
npm install
Launch frontend dev server
npm run dev
11. =================== Expose local port to public network ================
Install rc-tunnel tool
/var/run/secrets/frp-self-service/install
Execute command below to expose local port 5173 to public network:
"$HOME/.local/bin/rc-tunnel" expose --port 5173 -prefix myapp         (Corresponding public access URL: https://myapp.radeon.firstdg.ai/)
Check rc-tunnel running status
/root/.local/bin/rc-tunnel status
12. ================ Upload base data via frontend interface ====
Access frontend page: https://myapp.radeon.firstdg.ai/knowledge
Navigate to [Knowledge Base Management] and upload file "Banking & Insurance Channel Development and Industry Landscape.pdf"
(When MinerU runs for the first time, it will download required parsing models, which takes roughly 4-8 minutes)
13.================ Initialize learning center course data ==============
curl -X POST "http://localhost:8080/api/v1/courses"
-H "Content-Type: application/json"
-d '{
"title": "Mandatory Onboarding Course: Fundamentals of Bancassurance",
"description": "Cores core bancassurance concepts, product types and compliance requirements",
"category": "onboarding",
"video_path": "/videos/FinancialBancassurance.mp4",
"duration_sec": 3600,
"difficulty": 2,
"tags": ["bancassurance", "compliance", "new hire"]
}'
============================================================
=============Note: The first time you click [Start Exam], the loading process will take a long time as the backend initializes exam question bank==============================