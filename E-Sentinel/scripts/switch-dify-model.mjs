#!/usr/bin/env node
// ============================================================================
// Dify 文字模型一键切换脚本（DeepSeek ↔ 千问 qwen-plus）
// 用法:
//   node scripts/switch-dify-model.mjs qwen-plus        # 切到千问
//   node scripts/switch-dify-model.mjs deepseek-chat    # 切回 DeepSeek
//   node scripts/switch-dify-model.mjs qwen-plus --dry-run
// 前提: 服务器 SSH 可用（默认 /Users/xieweikai/Downloads/key.pem）
// ============================================================================
import { execFileSync } from "node:child_process";

const TARGET = process.argv[2];
const DRY_RUN = process.argv.includes("--dry-run");
const SSH_KEY = process.env.DIFY_SSH_KEY || "/Users/xieweikai/Downloads/key.pem";
const HOST = process.env.DIFY_SSH_HOST || "62.234.28.57";
const USER = process.env.DIFY_SSH_USER || "ubuntu";

const MODELS = {
  "qwen-plus": { name: "qwen-plus", provider: "langgenius/tongyi/tongyi" },
  "deepseek-chat": { name: "deepseek-chat", provider: "langgenius/deepseek/deepseek" },
};

if (!MODELS[TARGET]) {
  console.error(`❌ 目标模型必须是 qwen-plus 或 deepseek-chat，收到: ${TARGET}`);
  process.exit(1);
}

const PY = `
import json
TARGET = ${JSON.stringify(MODELS[TARGET])}
WORKFLOWS = [
    "2a9cad67-cb84-45d4-bdfc-4543ec03ebbe",  # 摄像头售后助手-双模型
    "8dd23c7d-4341-4862-9768-7956a6fe79dc",  # 拼多多客服助手-双模型
    "324bd234-a8fe-4b73-abbb-ed53796d682a",  # 天猫客服助手-双模型
    "4cd9c4c7-5e0a-48c4-a9ff-e7778cf6c01d",  # 京东客服助手-双模型
]
from app import app as flask_app
with flask_app.app_context():
    from extensions.ext_database import db
    from models.workflow import Workflow
    for wid in WORKFLOWS:
        wf = db.session.query(Workflow).filter(Workflow.id == wid).first()
        if not wf:
            print("NOT_FOUND", wid)
            continue
        graph = json.loads(wf.graph)
        changed = []
        for node in graph.get("nodes", []):
            d = node.get("data", {})
            if d.get("type") == "llm" and node.get("id") == "llm_text":
                old = dict(d.get("model", {}))
                d["model"] = {
                    **old,
                    "name": TARGET["name"],
                    "provider": TARGET["provider"],
                }
                changed.append((old.get("name"), d["model"]["name"]))
        wf.graph = json.dumps(graph, ensure_ascii=False)
        print("APP", wid[:8], "|", " -> ".join(f"{a} => {b}" for a, b in changed) or "no llm_text")
    db.session.commit()
    print("COMMITTED")
`;

function sshRun(script) {
  const b64 = Buffer.from(script, "utf8").toString("base64");
  const remote = `echo ${b64} | base64 -d | sudo docker exec -i docker-api-1 sh -c 'cd /app/api && .venv/bin/python -'`;
  return execFileSync("ssh", [
    "-i", SSH_KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
    `${USER}@${HOST}`, remote,
  ], { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
}

console.log(`${DRY_RUN ? "[DRY-RUN] " : ""}目标模型: ${TARGET} (${MODELS[TARGET].provider})`);
if (DRY_RUN) {
  const output = sshRun(
    PY
      .replace('db.session.commit()', 'db.session.rollback()\n    print("(dry-run, 未提交)")')
      .replace('print("COMMITTED")', 'print("(dry-run 结束)")'),
  );
  console.log(output);
} else {
  const output = sshRun(PY);
  console.log(output);
  console.log("✅ 切换完成。建议立即验证：node scripts/check-dify-answer.mjs");
}
