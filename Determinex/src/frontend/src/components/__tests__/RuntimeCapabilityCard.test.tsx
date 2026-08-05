/**
 * The runtime capability card must not turn a failed probe into a measurement.
 *
 * WHY THESE ASSERTIONS
 * --------------------
 * This card exists because two facts had no user-visible surface: the detected accelerator (probing
 * was `nvidia-smi`-only, so AMD and Apple rigs reported CPU-only and ran at the lowest tier) and the
 * usage ledger (referenced by passport.rs, never displayed, so "local is free" was a claim rather
 * than a reading).
 *
 * The failure mode to guard is the one this repo keeps finding: an unavailable value rendered as `0`,
 * which reads as "measured, and it was nothing". `invokeSafe` never rejects — it resolves `null` —
 * so a null result is the failure signal and must not be mistaken for an empty reading. The backend
 * deliberately carries a reason instead of a zero; these tests assert the UI honours that.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const invokeSafeMock = vi.fn();
vi.mock("@/lib/api", () => ({
  invokeSafe: (...a: unknown[]) => invokeSafeMock(...a),
  isTauri: () => true,
}));

import { RuntimeCapabilityCard } from "../RuntimeCapabilityCard";

const ACCELERATOR = {
  vendor: "amd",
  label: "AMD (ROCm) — 24.0 GB VRAM, 1 device(s)",
  torch_device: "cuda",
  vram_gb: 24.0,
  device_count: 1,
  ram_gb: 64.0,
  tier: 2,
  tier_label: "Full rig",
  max_local_models: 5,
  max_parallel_steps: 2,
  models_kept_resident: ["builder", "monitor", "oracle", "architect"],
  capacity_basis: "vram",
  platform_note: "",
};

/** An accelerator-less host: no GPU, capacity derived from system RAM. Before 2026-07-31 this
 *  machine reported tier -1 with 0 local models regardless of how much RAM it had. */
const CPU_ONLY_HOST = {
  vendor: "cpu",
  label: "CPU only (Qualcomm Snapdragon, ARM64) — 32.0 GB system RAM",
  torch_device: "cpu",
  vram_gb: 0,
  device_count: 0,
  ram_gb: 32.0,
  tier: 1,
  tier_label: "Mid-range",
  max_local_models: 4,
  max_parallel_steps: 1,
  models_kept_resident: ["builder", "monitor"],
  capacity_basis: "system_ram",
  platform_note: "Qualcomm Snapdragon, ARM64",
};

describe("RuntimeCapabilityCard", () => {
  beforeEach(() => invokeSafeMock.mockReset());

  it("renders the measured accelerator, including the PyTorch device string", async () => {
    invokeSafeMock.mockResolvedValue({ payload: { accelerator: ACCELERATOR, usage: null } });
    render(<RuntimeCapabilityCard />);
    await waitFor(() => expect(screen.getByText(/AMD \(ROCm\)/)).toBeInTheDocument());
    // The device string matters: a ROCm build of torch keeps the "cuda" name, so surfacing it is how
    // a user on AMD knows what to pass.
    expect(screen.getByText("cuda")).toBeInTheDocument();
    expect(screen.getByText(/Full rig/)).toBeInTheDocument();
    expect(screen.getByText("builder, monitor, oracle, architect")).toBeInTheDocument();
  });

  it("says the accelerator was not detected instead of showing 0 GB", async () => {
    invokeSafeMock.mockResolvedValue({
      payload: {
        accelerator: null,
        accelerator_error: "FileNotFoundError: rocm-smi",
        usage: null,
      },
    });
    render(<RuntimeCapabilityCard />);
    await waitFor(() => expect(screen.getByText(/Accelerator not detected/)).toBeInTheDocument());
    expect(screen.getByText(/rocm-smi/)).toBeInTheDocument();
    // THE regression: a missing reading must not appear as a measured zero.
    expect(screen.queryByText(/0\.0 GB/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0 GB VRAM/)).not.toBeInTheDocument();
  });

  it("distinguishes an unreadable RAM figure from a real one", async () => {
    // ram_gb 0 is what the old wmic-based probe returned on Windows 11 24H2+, where WMIC is absent.
    invokeSafeMock.mockResolvedValue({
      payload: { accelerator: { ...ACCELERATOR, ram_gb: 0 }, usage: null },
    });
    render(<RuntimeCapabilityCard />);
    await waitFor(() => expect(screen.getByText("not readable")).toBeInTheDocument());
    expect(screen.queryByText("0.0 GB")).not.toBeInTheDocument();
  });

  it("reports unavailable when the command returns nothing, and shows no figures", async () => {
    // invokeSafe resolves null rather than rejecting, so this is the real failure path.
    invokeSafeMock.mockResolvedValue(null);
    render(<RuntimeCapabilityCard />);
    await waitFor(() =>
      expect(screen.getByText(/did not return a runtime capability reading/)).toBeInTheDocument()
    );
    expect(screen.getByText(/none were measured/)).toBeInTheDocument();
    expect(screen.queryByText(/Tier/)).not.toBeInTheDocument();
  });

  it("renders real ledger totals when a ledger exists", async () => {
    invokeSafeMock.mockResolvedValue({
      payload: {
        accelerator: ACCELERATOR,
        usage: {
          exists: true,
          window_hours: 24,
          total_calls: 26,
          total_est_usd: 0,
          providers: { ollama: { calls: 13, est_usd: 0, models: ["ollama/llama3"] } },
        },
      },
    });
    render(<RuntimeCapabilityCard />);
    await waitFor(() => expect(screen.getByText("26")).toBeInTheDocument());
    expect(screen.getByText("$0.0000")).toBeInTheDocument();
    expect(screen.getByText("ollama")).toBeInTheDocument();
  });

  it("says there is no ledger rather than rendering an all-zero one", async () => {
    invokeSafeMock.mockResolvedValue({
      payload: { accelerator: ACCELERATOR, usage: { exists: false } },
    });
    render(<RuntimeCapabilityCard />);
    await waitFor(() => expect(screen.getByText(/No usage ledger yet/)).toBeInTheDocument());
  });

  it("asks the backend for the capability command by name", async () => {
    invokeSafeMock.mockResolvedValue({ payload: { accelerator: ACCELERATOR, usage: null } });
    render(<RuntimeCapabilityCard />);
    await waitFor(() => expect(invokeSafeMock).toHaveBeenCalled());
    expect(invokeSafeMock).toHaveBeenCalledWith("get_runtime_capability_status");
  });

  // ── Accelerator-less hosts ────────────────────────────────────────────────────────────────
  //
  // A CPU-only machine used to be reported as tier -1 / 0 local models whatever its RAM, so this
  // card had nothing useful to say about the largest class of machine a user might install on.

  it("says a tier came from system RAM, so it is not mistaken for VRAM", async () => {
    invokeSafeMock.mockResolvedValue({
      payload: { accelerator: CPU_ONLY_HOST, usage: null },
    });
    render(<RuntimeCapabilityCard />);
    await waitFor(() => expect(screen.getByText(/Mid-range/)).toBeInTheDocument());
    expect(screen.getByText(/from system RAM/)).toBeInTheDocument();
  });

  it("does not add the system-RAM note when an accelerator answered", async () => {
    invokeSafeMock.mockResolvedValue({ payload: { accelerator: ACCELERATOR, usage: null } });
    render(<RuntimeCapabilityCard />);
    await waitFor(() => expect(screen.getByText(/Full rig/)).toBeInTheDocument());
    expect(screen.queryByText(/from system RAM/)).not.toBeInTheDocument();
  });

  it("shows a CPU-only host holding models, not the old zero", async () => {
    invokeSafeMock.mockResolvedValue({
      payload: { accelerator: CPU_ONLY_HOST, usage: null },
    });
    render(<RuntimeCapabilityCard />);
    await waitFor(() => expect(screen.getByText("builder, monitor")).toBeInTheDocument());
    // The label names the platform so a Snapdragon user sees recognition, not a detection miss.
    expect(screen.getByText(/Snapdragon/)).toBeInTheDocument();
    // And it claims no accelerator it does not use.
    expect(screen.queryByText(/NPU|Hexagon|Adreno/)).not.toBeInTheDocument();
  });

  it("renders an older backend payload that lacks the new fields", async () => {
    // capacity_basis/platform_note are optional; their absence must not print "undefined".
    const { capacity_basis: _cb, platform_note: _pn, ...legacy } = ACCELERATOR;
    invokeSafeMock.mockResolvedValue({ payload: { accelerator: legacy, usage: null } });
    render(<RuntimeCapabilityCard />);
    await waitFor(() => expect(screen.getByText(/Full rig/)).toBeInTheDocument());
    expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
  });
});
