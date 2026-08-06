#!/usr/bin/env node

import process from "node:process";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

function parseArgs(argv) {
  const values = { debugUrl: "http://127.0.0.1:9229" };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (flag === "--debug-url") values.debugUrl = argv[++index];
    else if (flag === "--inspect") values.inspect = true;
    else if (flag === "--blueprint") values.blueprint = argv[++index];
    else if (flag === "--output") values.output = argv[++index];
    else if (flag === "--receipt") values.receipt = argv[++index];
    else throw new Error(`unknown argument: ${flag}`);
  }
  return values;
}

function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

function stableJson(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

async function pageTarget(debugUrl) {
  const response = await fetch(`${debugUrl.replace(/\/$/, "")}/json/list`);
  if (!response.ok) throw new Error(`DevTools target list failed: HTTP ${response.status}`);
  const targets = await response.json();
  const target = targets.find(
    (item) => item.type === "page" && /^http:\/\/127\.0\.0\.1:\d+\/(?:#.*)?$/.test(item.url)
  );
  if (!target?.webSocketDebuggerUrl) throw new Error("local ComfyUI page target is missing");
  return target;
}

async function connect(url) {
  const socket = new WebSocket(url);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let commandId = 0;
  const pending = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(String(event.data));
    if (!message.id || !pending.has(message.id)) return;
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result);
  });
  return {
    async evaluate(expression) {
      commandId += 1;
      const result = await new Promise((resolve, reject) => {
        pending.set(commandId, { resolve, reject });
        socket.send(
          JSON.stringify({
            id: commandId,
            method: "Runtime.evaluate",
            params: {
              expression,
              awaitPromise: true,
              returnByValue: true
            }
          })
        );
      });
      if (result.exceptionDetails) {
        const detail = result.exceptionDetails.exception?.description
          ?? result.exceptionDetails.text
          ?? "browser evaluation failed";
        throw new Error(detail);
      }
      return result.result?.value;
    },
    close() {
      socket.close();
    }
  };
}

const args = parseArgs(process.argv.slice(2));
const target = await pageTarget(args.debugUrl);
const cdp = await connect(target.webSocketDebuggerUrl);
try {
  if (args.inspect) {
    const result = await cdp.evaluate(`(() => ({
      title: document.title,
      readyState: document.readyState,
      windowKeys: Object.keys(window).filter((key) => /comfy|app/i.test(key)).sort(),
      comfyApiKeys: Object.keys(window.comfyAPI ?? {}).sort(),
      appType: typeof window.app,
      comfyApiAppType: typeof window.comfyAPI?.app,
      appMethods: Object.getOwnPropertyNames(Object.getPrototypeOf(window.app ?? {})).sort(),
      graphMethods: Object.getOwnPropertyNames(Object.getPrototypeOf(window.app?.graph ?? {})).sort(),
      rootGraphMethods: Object.getOwnPropertyNames(Object.getPrototypeOf(window.app?.rootGraph ?? {})).sort()
    }))()`);
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } else {
    if (!args.blueprint || !args.output || !args.receipt) {
      throw new Error("--blueprint, --output, and --receipt are required");
    }
    const blueprintPath = path.resolve(args.blueprint);
    const outputPath = path.resolve(args.output);
    const receiptPath = path.resolve(args.receipt);
    const blueprintBytes = await readFile(blueprintPath);
    const blueprint = JSON.parse(blueprintBytes.toString("utf8"));
    const browserResult = await cdp.evaluate(`(async () => {
      const blueprint = ${JSON.stringify(blueprint)};
      if (!window.app?.loadGraphData || !window.app?.graphToPrompt) {
        throw new Error("official ComfyUI application methods are unavailable");
      }
      await window.app.loadGraphData(
        blueprint,
        true,
        false,
        null,
        {
          openSource: "template",
          deferWarnings: true,
          skipAssetScans: true,
          silentAssetErrors: true
        }
      );
      const graphNodes = window.app.rootGraph.computeExecutionOrder(false);
      const missingNodes = graphNodes
        .filter((node) => !node.comfyClass)
        .map((node) => ({ id: String(node.id), type: String(node.type), title: String(node.title) }));
      const prompt = await window.app.graphToPrompt(window.app.rootGraph);
      return {
        frontendVersion: window.__COMFYUI_FRONTEND_VERSION__,
        graphNodeCount: graphNodes.length,
        missingNodes,
        output: prompt.output
      };
    })()`);
    if (!browserResult || typeof browserResult !== "object") {
      throw new Error("official frontend returned no export result");
    }
    if (!Number.isInteger(browserResult.graphNodeCount) || browserResult.graphNodeCount < 1) {
      throw new Error("official frontend loaded no graph nodes");
    }
    if (!Array.isArray(browserResult.missingNodes) || browserResult.missingNodes.length > 0) {
      throw new Error(`workflow contains missing nodes: ${JSON.stringify(browserResult.missingNodes)}`);
    }
    if (!browserResult.output || typeof browserResult.output !== "object" || Array.isArray(browserResult.output)) {
      throw new Error("official frontend returned an invalid API workflow");
    }
    const outputEntries = Object.entries(browserResult.output);
    if (outputEntries.length < 1 || outputEntries.some(([, node]) => !node?.class_type || !node?.inputs)) {
      throw new Error("official API workflow contains invalid executable nodes");
    }
    const outputBytes = Buffer.from(stableJson(browserResult.output), "utf8");
    await writeFile(outputPath, outputBytes, { flag: "wx", mode: 0o600 });
    const systemResponse = await fetch("http://127.0.0.1:8189/system_stats");
    if (!systemResponse.ok) throw new Error(`ComfyUI system stats failed: HTTP ${systemResponse.status}`);
    const systemStats = await systemResponse.json();
    const receipt = {
      schema: "ProofLaunchOfficialComfyUIApiExportReceiptV1",
      method: "official_frontend_app.loadGraphData_then_app.graphToPrompt",
      source_blueprint: path.basename(blueprintPath),
      source_blueprint_sha256: sha256(blueprintBytes),
      output_api_workflow: path.basename(outputPath),
      output_api_workflow_sha256: sha256(outputBytes),
      output_node_count: outputEntries.length,
      graph_node_count: browserResult.graphNodeCount,
      missing_node_count: 0,
      comfyui_core_revision: "2881e6161081439b1c3fb3b6c1f51b3d272da710",
      comfyui_version: systemStats.system?.comfyui_version ?? null,
      comfyui_frontend_version: browserResult.frontendVersion,
      inference_executed: false,
      models_loaded: false,
      gpu_used: false,
      truth_boundary: "This receipt proves only official frontend API-format conversion. It is not model admission, inference, media output, Radeon evidence, or 4A effect proof."
    };
    await writeFile(receiptPath, stableJson(receipt), { flag: "wx", mode: 0o600 });
    process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
  }
} finally {
  cdp.close();
}
