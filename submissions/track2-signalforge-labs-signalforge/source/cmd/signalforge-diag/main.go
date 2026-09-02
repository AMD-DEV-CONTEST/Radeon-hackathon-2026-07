package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

type probe struct {
	Name    string   `json:"name"`
	Command string   `json:"command"`
	Args    []string `json:"args,omitempty"`
}

type probeResult struct {
	Name       string `json:"name"`
	Command    string `json:"command"`
	Available  bool   `json:"available"`
	ExitCode   int    `json:"exit_code"`
	DurationMS int64  `json:"duration_ms"`
	Output     string `json:"output,omitempty"`
	Error      string `json:"error,omitempty"`
}

type report struct {
	SchemaVersion string            `json:"schema_version"`
	GeneratedAt   time.Time         `json:"generated_at"`
	HostRuntime   map[string]string `json:"host_runtime"`
	Results       []probeResult     `json:"results"`
}

func main() {
	output := flag.String("output", "", "write the JSON report to this path instead of stdout")
	timeout := flag.Duration("probe-timeout", 30*time.Second, "maximum duration for each probe")
	python := flag.String("python", "python3", "Python executable containing the AI runtime")
	workspace := flag.String("workspace", "/workspace", "persistent workspace path to inspect")
	flag.Parse()

	report := collect(*timeout, buildProbes(*python, *workspace))
	payload, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		fatal(err)
	}
	payload = append(payload, '\n')
	if *output == "" {
		_, _ = os.Stdout.Write(payload)
		return
	}
	if err := os.WriteFile(*output, payload, 0o644); err != nil {
		fatal(err)
	}
}

func buildProbes(python, workspace string) []probe {
	return []probe{
		{Name: "kernel", Command: "uname", Args: []string{"-a"}},
		{Name: "operating_system", Command: "cat", Args: []string{"/etc/os-release"}},
		{Name: "cpu", Command: "lscpu"},
		{Name: "memory", Command: "free", Args: []string{"-b"}},
		{Name: "cgroup_cpu_limit", Command: "cat", Args: []string{"/sys/fs/cgroup/cpu.max"}},
		{Name: "cgroup_memory_limit", Command: "cat", Args: []string{"/sys/fs/cgroup/memory.max"}},
		{Name: "workspace_storage", Command: "df", Args: []string{"-B1", workspace}},
		{Name: "rocm_version", Command: "cat", Args: []string{"/opt/rocm/.info/version"}},
		{Name: "rocm_info", Command: "rocminfo"},
		{Name: "amd_smi", Command: "amd-smi", Args: []string{"static", "--json"}},
		{Name: "rocm_smi", Command: "rocm-smi", Args: []string{"--showproductname", "--showdriverversion", "--showmeminfo", "vram", "--showuse", "--showmemuse"}},
		{Name: "python", Command: python, Args: []string{"--version"}},
		{Name: "pytorch_rocm", Command: python, Args: []string{"-c", "import json,torch; print(json.dumps({'torch':torch.__version__,'hip':torch.version.hip,'cuda_available':torch.cuda.is_available(),'device_count':torch.cuda.device_count(),'devices':[torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]}))"}},
		{Name: "vllm", Command: python, Args: []string{"-c", "import vllm; print(vllm.__version__)"}},
		{Name: "ai_packages", Command: python, Args: []string{"-c", "import json,platform,torch,transformers,vllm; import triton; print(json.dumps({'python':platform.python_version(),'torch':torch.__version__,'hip':torch.version.hip,'transformers':transformers.__version__,'vllm':vllm.__version__,'triton':triton.__version__}))"}},
		{Name: "rocprofiler_agents", Command: "/opt/rocm/bin/rocprofv3-avail", Args: []string{"-d", "0", "list"}},
	}
}

func collect(timeout time.Duration, probes []probe) report {
	result := report{
		SchemaVersion: "signalforge/environment-report/v1",
		GeneratedAt:   time.Now().UTC(),
		HostRuntime: map[string]string{
			"go_version": runtime.Version(),
			"go_os":      runtime.GOOS,
			"go_arch":    runtime.GOARCH,
		},
		Results: make([]probeResult, 0, len(probes)),
	}
	for _, item := range probes {
		result.Results = append(result.Results, runProbe(item, timeout))
	}
	return result
}

func runProbe(item probe, timeout time.Duration) probeResult {
	started := time.Now()
	result := probeResult{Name: item.Name, Command: strings.Join(append([]string{item.Command}, item.Args...), " "), ExitCode: -1}
	path, err := exec.LookPath(item.Command)
	if err != nil {
		result.Error = "command unavailable"
		result.DurationMS = time.Since(started).Milliseconds()
		return result
	}
	result.Available = true
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, path, item.Args...)
	output, err := cmd.CombinedOutput()
	result.DurationMS = time.Since(started).Milliseconds()
	result.Output = strings.TrimSpace(string(output))
	if ctx.Err() == context.DeadlineExceeded {
		result.Error = "probe timeout"
		return result
	}
	if err == nil {
		result.ExitCode = 0
		return result
	}
	result.Error = err.Error()
	if exitErr, ok := err.(*exec.ExitError); ok {
		result.ExitCode = exitErr.ExitCode()
	}
	return result
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
