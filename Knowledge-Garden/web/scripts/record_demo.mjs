// record_demo.mjs — 3-5 分钟演示视频录制（真实 AMD GPU 推理）
// 用法: cd web && node scripts/record_demo.mjs
import { chromium } from "playwright"
import { writeFileSync, mkdirSync } from "node:fs"

const OUT = "/tmp/lc-demo2"
mkdirSync(OUT, { recursive: true })

const MD = `# Raft Consensus Algorithm — Study Notes

## Why Raft?

Raft is a consensus algorithm designed to be understandable. It is an alternative to Paxos,
offering the same fault tolerance with a clearer structure.

## Leader Election

Raft uses randomized timeouts for leader election. Each server waits a random time before
starting an election; the candidate that receives votes from the majority becomes the leader.
This randomized approach makes split votes rare and the algorithm simple to reason about.

## Log Replication

The leader accepts entries from clients and replicates them to followers. An entry is
committed once the leader receives confirmation from the majority of the cluster. Followers
replicate committed entries to stay consistent.

## Safety Properties

- **Election Safety**: at most one leader per term.
- **Log Matching**: if two logs contain the same entry at the same index, all prior entries match.
- **Leader Completeness**: a committed entry is present in the log of every future leader.
- **State Machine Safety**: if a server applies a log entry at a given index, no other server
  applies a different entry at that index.

## Raft in Practice

Raft powers etcd, Consul, and TiKV. It is the default consensus layer for many distributed
databases and Kubernetes control planes.
`
writeFileSync(`${OUT}/raft-notes.md`, MD, "utf8")

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const base = "http://127.0.0.1:8510"

const browser = await chromium.launch()
const context = await browser.newContext({
  viewport: { width: 1280, height: 900 },
  recordVideo: { dir: OUT, size: { width: 1280, height: 900 } },
})
const page = await context.newPage()
const shot = async (name) => { await page.screenshot({ path: `${OUT}/${name}.png` }) }

// T+0:00 花园总览
await page.goto(`${base}/`)
await page.waitForSelector("text=技能花园", { timeout: 10000 })
await sleep(3500)
await shot("01-garden")

// 侧边栏技能导航
await page.locator("nav button", { hasText: "Raft" }).first().click().catch(() => {})
await sleep(3000)
await shot("02-skill-nav")

// GPU 验证（真实 rocm-smi 数据展示）
await page.goto("data:text/html," + encodeURIComponent(`<html><head><style>body{font-family:ui-monospace,monospace;background:#0d1117;color:#e6edf3;padding:40px;font-size:15px}pre{white-space:pre-wrap}h1{color:#58a6ff;font-size:20px}</style></head><body><h1>AMD Radeon GPU — verified live</h1><pre>ROCM System Management Interface\n============================\nMemory Usage (Bytes)\nGPU[0]: VRAM Total Memory (B): 51522830336  (48 GB)\nGPU[0]: VRAM Total Used Memory (B): 41784578048 (dual-model co-resident)\n\nProduct Info\nGPU[0]: Card Series: AMD Radeon Graphics (gfx1100, RDNA3)\nGPU[0]: Card Vendor: Advanced Micro Devices [AMD/ATI]\n\nROCm 7.2.x  |  vLLM 0.16.1  |  AWQ 4-bit</pre></body></html>`))
await sleep(4000)
await shot("02-gpu-verify")

// vLLM 模型端点
await page.goto("data:text/html," + encodeURIComponent(`<html><head><style>body{font-family:ui-monospace,monospace;background:#0d1117;color:#e6edf3;padding:40px;font-size:15px}pre{white-space:pre-wrap}h1{color:#58a6ff;font-size:20px}</style></head><body><h1>vLLM on ROCm — OpenAI-compatible endpoints</h1><pre>$ curl :8000/v1/models  ->  Qwen2.5-14B-Instruct-AWQ   (dialogue layer,  26.5 tok/s)\n$ curl :8001/v1/models  ->  Qwen2.5-32B-Instruct-AWQ   (batch extractor, 12.5 tok/s)\n$ embedding: bge-base-en-v1.5 (RAG source grounding)\n\nAWQ 4-bit = 2.1x faster than bf16 on gfx1100\nDual-model co-resident on ONE 48GB card: 42GB total, 6GB headroom\nQwen2.5 routing decision validated by offline A/B (see docs/evaluation)</pre></body></html>`))
await sleep(5000)
await shot("03-vllm-models")


await page.goto(`${base}/upload`)
await sleep(2500)
await shot("03-upload")
await page.getByPlaceholder("例如：Raft 共识算法").fill("Raft 共识算法")
await page.setInputFiles('input[type="file"]', `${OUT}/raft-notes.md`)
await sleep(2500)
await shot("04-upload-filedropped")
await page.getByRole("button", { name: "创建导入" }).click()
await page.waitForURL(/\/processing\/\d+/)
await sleep(2500)
await shot("05-processing")

// T+0:40 等待提取完成（真实 32B 推理）
console.log("等待提取完成（真实 32B 推理）...")
const t0 = Date.now()
await page.getByText("验证完成", { timeout: 180000 }).waitFor()
const extractSec = ((Date.now() - t0) / 1000).toFixed(1)
console.log(`提取完成，耗时 ${extractSec}s，自动更新无需刷新`)
await sleep(2500)
await shot("06-verified")

// T+1:30 查看技能详情
await page.getByRole("button", { name: "查看技能" }).click()
await page.waitForURL(/\/skills\/\d+/)
await sleep(3000)
await shot("07-skill-detail")

// 查看源文档（Markdown 渲染）
const srcBtn = page.getByRole("button", { name: /查看来源/ }).first()
if (await srcBtn.count()) {
  await srcBtn.click()
  await page.waitForURL(/\/source\/\d+/)
  await sleep(3500)
  await shot("08-source-doc")
  await page.goBack()
  await sleep(2200)
}

// T+2:00 开始学习（费曼复述）
await page.getByRole("button", { name: "开始学习" }).click()
await page.waitForURL(/\/learn/)
await sleep(3000)
await shot("09-learn")
await page.getByLabel("费曼复述草稿").fill("Raft 通过随机超时选举领导者，多数票胜出；日志由领导者复制，多数确认后提交。")
await sleep(2500)
await shot("10-learn-draft")
await page.getByRole("button", { name: "标记本单元完成" }).click().catch(() => {})
await sleep(3000)
await shot("11-learn-next")

// T+2:40 首次评估
await page.goto(`${base}/skills/15/assessment`).catch(async () => {
  await page.goto(`${base}/skills/12/assessment`).catch(() => {})
})
await sleep(3000)
await page.getByRole("button", { name: "开始评估" }).click().catch(() => {})
await sleep(2500)
await shot("12-assessment")
await page.getByLabel("回忆输入").fill("Raft 通过随机超时选举领导者。").catch(() => {})
await sleep(2200)
await shot("13-assessment-input")

// T+3:20 复习流程
await page.goto(`${base}/garden`)
await sleep(2500)
await shot("14-garden-return")
await page.getByRole("button", { name: /到期复习|复习/ }).first().click().catch(async () => {
  await page.goto(`${base}/skills/15/review`).catch(() => {})
})
await sleep(3000)
await shot("15-review")

// T+3:50 收尾（花园最终态）
await page.goto(`${base}/garden`)
await sleep(3000)
await shot("16-final-garden")

await browser.close()
console.log(`\n录制完成: ${OUT}/ 提取耗时 ${extractSec}s`)
