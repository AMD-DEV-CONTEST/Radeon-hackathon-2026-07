import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { probeRuntime, isLoopbackHost, isLoopbackUrl } from "../src/runtime.mjs";

const baseConfig = {
  vllmBaseUrl: "http://127.0.0.1:8000/v1",
  vllmPid: 4242,
  rocmSmiBin: "rocm-smi",
  amdSmiBin: "amd-smi",
  rocmVersion: "7.2.1",
  rocmProbeTimeoutMs: 5000
};

function mockDeps({ cmdline = "/usr/bin/python3\0-m\0vllm.entrypoints.openai.api_server\0", rocmJson, amdJson, amdListJson = null, rocmThrows = false, amdThrows = false } = {}) {
  return {
    readFileFn: async () => cmdline,
    execFileFn: async (bin, args) => {
      if (bin.includes("rocm-smi")) {
        if (rocmThrows) throw new Error("rocm-smi not found");
        return { stdout: rocmJson };
      }
      if (amdThrows) throw new Error("amd-smi not found");
      if (args.includes("--pid")) return { stdout: amdJson };
      return { stdout: amdListJson ?? amdJson };
    }
  };
}

const rocmOk = JSON.stringify({
  card: { "card series": "AMD Radeon Graphics", "card model": "0x744b", gfx: "gfx1100" },
  process: { pid: 4242, name: "llama-server" }
});
const amdOk = JSON.stringify({ process_list: [{ pid: 4242, mem: "1234" }] });

describe("runtime attestation", () => {
  it("identifies loopback hosts and URLs", () => {
    assert.equal(isLoopbackHost("127.0.0.1"), true);
    assert.equal(isLoopbackHost("0.0.0.0"), false);
    assert.equal(isLoopbackUrl("http://localhost:8000/v1"), true);
    assert.equal(isLoopbackUrl("http://10.0.0.5:8000/v1"), false);
    assert.equal(isLoopbackUrl("not a url"), false);
  });

  it("attests a Radeon process when amd-smi lists the endpoint PID", async () => {
    const runtime = await probeRuntime(baseConfig, mockDeps({ rocmJson: rocmOk, amdJson: amdOk }));
    assert.equal(runtime.radeon_attested, true);
    assert.equal(runtime.process_attested, true);
    assert.match(runtime.gpu_name, /Radeon/i);
  });

  it("refuses attestation when endpoint is not loopback", async () => {
    const runtime = await probeRuntime({ ...baseConfig, vllmBaseUrl: "http://10.0.0.5:8000/v1" }, mockDeps({ rocmJson: rocmOk, amdJson: amdOk }));
    assert.equal(runtime.radeon_attested, false);
    assert.match(runtime.attestation_error, /loopback/);
  });

  it("refuses attestation without VLLM_PID", async () => {
    const runtime = await probeRuntime({ ...baseConfig, vllmPid: null }, mockDeps({ rocmJson: rocmOk, amdJson: amdOk }));
    assert.equal(runtime.radeon_attested, false);
    assert.match(runtime.attestation_error, /VLLM_PID/);
  });

  it("refuses attestation when the PID does not identify vLLM or llama-server", async () => {
    const runtime = await probeRuntime(
      baseConfig,
      mockDeps({ cmdline: "/usr/bin/python3\0-m\0http.server\0", rocmJson: rocmOk, amdJson: amdOk })
    );
    assert.equal(runtime.radeon_attested, false);
    assert.match(runtime.attestation_error, /command line/);
  });

  it("refuses attestation when amd-smi does not list the PID", async () => {
    const runtime = await probeRuntime(
      baseConfig,
      mockDeps({
        rocmJson: rocmOk,
        amdJson: JSON.stringify({ process_list: [{ pid: 9999 }] }),
        amdListJson: JSON.stringify([{ process_list: [{ process_info: { pid: 9999, memory_usage: { vram_mem: { value: 100 } } } }] }])
      })
    );
    assert.equal(runtime.radeon_attested, false);
  });

  it("falls back to device occupancy attestation inside a PID namespace", async () => {
    const runtime = await probeRuntime(
      baseConfig,
      mockDeps({
        rocmJson: rocmOk,
        amdJson: JSON.stringify({ process_list: [] }),
        amdListJson: JSON.stringify([{
          gpu: 0,
          process_list: [{ process_info: { pid: 3108837, memory_usage: { vram_mem: { value: 6425128960 } } } }]
        }])
      })
    );
    assert.equal(runtime.radeon_attested, true);
    assert.match(runtime.attestation_note, /container PID namespace/);
  });

  it("reports GPU UNATTESTED when tooling throws", async () => {
    const runtime = await probeRuntime(baseConfig, mockDeps({ rocmThrows: true, rocmJson: rocmOk, amdJson: amdOk }));
    assert.equal(runtime.radeon_attested, false);
    assert.ok(runtime.attestation_error);
  });
});
