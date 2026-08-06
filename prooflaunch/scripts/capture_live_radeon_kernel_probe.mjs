import crypto from "node:crypto";
import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";


const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const CDP_URL = "http://127.0.0.1:9222";
const PROBE_MARKER = "__PROOFLAUNCH_RADEON_PROBE__";
const PROBE_CODE = String.raw`
import json
import math
import platform
import torch

payload = {
    "python": platform.python_version(),
    "torch": torch.__version__,
    "hip": getattr(torch.version, "hip", None),
    "cuda_api_available": bool(torch.cuda.is_available()),
    "device_count": int(torch.cuda.device_count()),
    "devices": [],
    "gpu_matmul": None,
}

if payload["cuda_api_available"]:
    for index in range(payload["device_count"]):
        props = torch.cuda.get_device_properties(index)
        payload["devices"].append({
            "index": index,
            "name": torch.cuda.get_device_name(index),
            "total_memory_bytes": int(props.total_memory),
        })
    left = torch.arange(0, 256 * 256, device="cuda", dtype=torch.float32).reshape(256, 256)
    right = torch.eye(256, device="cuda", dtype=torch.float32)
    result = left @ right
    torch.cuda.synchronize()
    checksum = float(result.sum().item())
    expected = float(left.sum().item())
    payload["gpu_matmul"] = {
        "shape": [256, 256],
        "checksum": checksum,
        "expected": expected,
        "finite": bool(math.isfinite(checksum)),
        "matches_identity": bool(abs(checksum - expected) <= 1e-3),
    }

print("${PROBE_MARKER}" + json.dumps(payload, sort_keys=True))
`;


function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}


async function atomicWriteJson(filePath, payload) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.${process.pid}.${crypto.randomUUID()}.tmp`;
  const handle = await fs.open(temporary, "w", 0o600);
  try {
    await handle.writeFile(`${JSON.stringify(payload, null, 2)}\n`, "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
  await fs.rename(temporary, filePath);
}


async function main() {
  const projectRoot = path.resolve(process.argv[2] || process.cwd());
  const outputPath = path.join(projectRoot, "evidence/v10/radeon-live-kernel-probe.json");
  const browser = await chromium.connectOverCDP(CDP_URL);
  const pages = browser.contexts().flatMap((context) => context.pages());
  const page = pages.find((candidate) => candidate.url().includes("/radeon/instances/"));
  if (!page) throw new Error("No authenticated Radeon Jupyter page is open");

  const observation = await page.evaluate(
    async ({ code, marker }) => {
      const prefix = location.pathname.match(/^\/radeon\/instances\/[^/]+/)?.[0];
      if (!prefix) throw new Error("Cannot resolve Radeon instance prefix");
      const instanceId = prefix.split("/").at(-1);
      const createResponse = await fetch(`${prefix}/api/kernels`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "python3" }),
      });
      const created = await createResponse.json().catch(() => null);
      if (!createResponse.ok || !created?.id) {
        throw new Error(`Kernel creation failed with HTTP ${createResponse.status}`);
      }

      const kernelId = created.id;
      const sessionId = crypto.randomUUID();
      const messageId = crypto.randomUUID();
      const scheme = location.protocol === "https:" ? "wss:" : "ws:";
      const socketUrl =
        `${scheme}//${location.host}${prefix}/api/kernels/${kernelId}/channels` +
        `?session_id=${encodeURIComponent(sessionId)}`;

      const execution = await new Promise((resolve, reject) => {
        const socket = new WebSocket(socketUrl);
        const streams = [];
        const errors = [];
        let becameBusy = false;
        const timeout = setTimeout(() => {
          socket.close();
          reject(new Error("Radeon kernel probe timed out after 60 seconds"));
        }, 60_000);

        socket.onerror = () => {
          clearTimeout(timeout);
          reject(new Error("Radeon kernel WebSocket failed"));
        };
        socket.onopen = () => {
          socket.send(JSON.stringify({
            channel: "shell",
            header: {
              msg_id: messageId,
              username: "prooflaunch",
              session: sessionId,
              date: new Date().toISOString(),
              msg_type: "execute_request",
              version: "5.3",
            },
            parent_header: {},
            metadata: {},
            content: {
              code,
              silent: false,
              store_history: false,
              user_expressions: {},
              allow_stdin: false,
              stop_on_error: true,
            },
            buffers: [],
          }));
        };
        socket.onmessage = (event) => {
          if (typeof event.data !== "string") return;
          let message;
          try {
            message = JSON.parse(event.data);
          } catch {
            return;
          }
          if (message?.parent_header?.msg_id !== messageId) return;
          const messageType = message?.header?.msg_type;
          if (messageType === "stream") streams.push(String(message.content?.text || ""));
          if (messageType === "error") {
            errors.push({
              ename: message.content?.ename || null,
              evalue: message.content?.evalue || null,
            });
          }
          if (messageType === "status" && message.content?.execution_state === "busy") {
            becameBusy = true;
          }
          if (
            becameBusy &&
            messageType === "status" &&
            message.content?.execution_state === "idle"
          ) {
            clearTimeout(timeout);
            socket.close();
            resolve({ streams, errors });
          }
        };
      });

      const markerLine = execution.streams
        .join("")
        .split(/\r?\n/)
        .find((line) => line.startsWith(marker));
      if (!markerLine) throw new Error("Probe marker missing from kernel output");
      return {
        instance_id: instanceId,
        kernel_id: kernelId,
        runtime: JSON.parse(markerLine.slice(marker.length)),
        kernel_errors: execution.errors,
      };
    },
    { code: PROBE_CODE, marker: PROBE_MARKER },
  );

  const runtime = observation.runtime;
  const passed = Boolean(
    runtime?.cuda_api_available &&
      runtime?.device_count >= 1 &&
      runtime?.hip &&
      runtime?.gpu_matmul?.finite &&
      runtime?.gpu_matmul?.matches_identity &&
      observation.kernel_errors.length === 0,
  );
  const receipt = {
    schema: "ProofLaunchRadeonLiveKernelProbeV1",
    captured_at: new Date().toISOString(),
    status: passed ? "passed" : "failed",
    evidence_class: "observed_radeon_local_runtime",
    instance_id: observation.instance_id,
    kernel_id: observation.kernel_id,
    probe_code_sha256: sha256(PROBE_CODE),
    runtime,
    kernel_errors: observation.kernel_errors,
    truth_boundary:
      "This receipt proves only the observed local ROCm/PyTorch kernel and deterministic GPU matmul. It is not model training, key model inference, multi-GPU evidence, or a business-effect claim.",
  };
  await atomicWriteJson(outputPath, receipt);
  process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
  if (!passed) process.exitCode = 1;
}


await main();
