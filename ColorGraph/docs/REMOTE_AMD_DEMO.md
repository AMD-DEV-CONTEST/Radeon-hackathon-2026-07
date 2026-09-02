# Remote AMD UI and Recording Workflow

This workflow displays the ColorGraph grading workstation in a browser on the
recording computer while all API, AI, grading, rendering, and quality jobs run on
the remote AMD Radeon server.

```text
local browser + screen recorder
  -> SSH tunnel: local 4173 -> server 127.0.0.1:4173
  -> SSH tunnel: local 8010 -> server 127.0.0.1:8010
  -> ColorGraph API and ROCm jobs on the Radeon server
```

The server does not need a desktop, VNC, or a public web port. Do not bind the
Vite development server, FastAPI, or Ollama directly to a public interface.

## 1. Prepare the Radeon server

Use the already verified ROCm environment and copy the frozen public demo project,
media, model cache, and evidence package to the server. Avoid uploading the hero
clip through the browser during the recording; keep it on the server and open the
prepared project from the project list.

Install frontend dependencies once:

```bash
cd /path/to/color
npm ci
```

Set the server model cache explicitly. If the local Ollama creative provider will
be demonstrated, start Ollama first and enable the pinned provider configuration
used by the verified AMD run.

```bash
cd /path/to/color
export COLORGRAPH_HUGGINGFACE_CACHE_DIR=/path/to/colorgraph-models/huggingface
export COLORGRAPH_ENABLE_OLLAMA_CREATIVE_PROVIDER=true
export COLORGRAPH_OLLAMA_CREATIVE_MODEL=colorgraph-qwen3.5:9b
export COLORGRAPH_OLLAMA_CREATIVE_MODEL_DIGEST=a2845456d7ad1e2100f620eaad82c3e63860a24330948111f6ad5d8202fd3634
export COLORGRAPH_OLLAMA_CREATIVE_RUNTIME_VERSION=0.20.6
export COLORGRAPH_OLLAMA_CREATIVE_QUANTIZATION=Q4_K_M
bash scripts/start-amd-demo-ui-linux.sh
```

Keep this shell running. The launcher deliberately binds both services to the
server loopback interface and writes logs under `.run/`.

Before recording, verify the server-side identity in another SSH shell:

```bash
amd-smi static --gpu all
curl -s http://127.0.0.1:8010/api/system/device | python3 -m json.tool
sha256sum output/evidence/amd-full-rocm-linux-radeon-cloud-20260802-v6/amd-full-pipeline-report.json
```

The API response must report `runtime: rocm` and the actual AMD device name. The
report digest for the frozen verified run is:

```text
c7a7e15c265ac8a33a9286125059b67d6ee4b7df90827caa02be53337235c195
```

## 2. Open the SSH tunnel from the recording computer

Run this in a local terminal and leave it open:

```powershell
ssh -N `
  -L 4173:127.0.0.1:4173 `
  -L 8010:127.0.0.1:8010 `
  USER@SERVER
```

If the SSH service uses a non-default port, add `-p PORT`. Do not forward Ollama;
the remote backend talks to remote Ollama over the server loopback interface.

Open `http://127.0.0.1:4173`. The frontend defaults to
`http://127.0.0.1:8010`, so the second tunnel carries every API request to the AMD
server without a frontend rebuild. The top bar displays the device name and ROCm
runtime returned by the remote API.

## 3. Record an auditable 3-5 minute demo

Capture the local browser and one local terminal window with the screen recorder
already available on the recording computer. Record at 1920x1080 when possible.
Use a continuous take for the core operation chain; cuts may shorten waiting time,
but must not imply that a prerecorded render was produced live.

Recommended shot order:

1. Show the SSH server identity, `amd-smi`, the device API response, and the frozen
   report hash.
2. Open ColorGraph and keep the top-bar AMD device name and `ROCM` label visible.
3. Open the prepared 12.5-second Snowdonia project and play the original proxy.
4. Run or open the three `faithful`, `amplified`, and `counterpoint` directions;
   compare visible results and manually select one.
5. Apply one scoped natural-language correction, such as lowering the sky in the
   second half without changing the mountains.
6. Play the real graded preview and show the job panel reporting the ROCm backend.
7. Export the MP4, LUT, Grade Graph, masks, and quality report; show the Main10 and
   hard-quality results.
8. End on the generated evidence/report hash and clearly distinguish the live demo
   run from the archived verified benchmark.

Generate and buffer the short preview once before the final take so network latency
does not look like GPU execution time. Keep the actual project operation live and
do not replace it with a video embedded in the UI.

## 4. What the recording proves

The browser runs locally only as a display client. The following evidence ties the
visible operation to the remote Radeon server:

- The UI reads the remote `/api/system/device` response through the SSH tunnel.
- Job records and the pipeline modal report the backend runtime returned by the
  remote API.
- Media, project state, previews, renders, and reports are stored on the server.
- The terminal records AMD device/runtime identity and the evidence report hash.

Do not claim that local screen compositing or browser video decode ran on Radeon.
The defensible claim is that ColorGraph AI, grading, rendering, and QA jobs shown
by the remote API ran on the named Radeon/ROCm server.

## 5. Radeon Cloud SSH recovery

The current Radeon Cloud image is a container-style environment with Jupyter Lab
and no systemd. The ColorGraph public key is normally preinstalled, so an SSH
timeout should be treated as a missing listener or port-mapping problem before it
is treated as a key problem.

The expected network path is:

```text
recording workstation -> 36.150.116.206:31111/TCP
                      -> container 0.0.0.0:22/TCP
```

If SSH times out, open a Jupyter Terminal from the cloud console and inspect the
listeners:

```bash
ss -lntp | grep -E ':(22|8888)[[:space:]]' || true
```

If only Jupyter on port `8888` is present, start OpenSSH directly. Do not use
`systemctl` in this image:

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server
mkdir -p /run/sshd /root/.ssh
chmod 700 /root/.ssh
chmod 600 /root/.ssh/authorized_keys
chown -R root:root /root/.ssh
ssh-keygen -A
/usr/sbin/sshd -t
/usr/sbin/sshd
ss -lntp | grep ':22 '
```

Keep the Jupyter Terminal open until a second terminal confirms the external
connection:

```powershell
ssh -i C:\Users\panbu\.ssh\colorgraph_radeon_ed25519 `
  -o IdentitiesOnly=yes `
  -p 31111 root@36.150.116.206
```

Failure interpretation:

- `Connection timed out`: start/check `sshd`, cloud TCP mapping, instance state,
  public address, and the `31111 -> 22` rule.
- `Connection refused`: the route is reachable but no process listens on the
  mapped internal port.
- `Permission denied (publickey)`: only then inspect `authorized_keys`, ownership,
  permissions, and the selected private key.
