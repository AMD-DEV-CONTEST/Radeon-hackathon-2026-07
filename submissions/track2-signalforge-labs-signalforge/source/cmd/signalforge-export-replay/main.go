package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/rvbernucci/signalforge/internal/golden"
)

func main() {
	input := flag.String("input", "", "private golden report JSON")
	output := flag.String("output", "", "privacy-safe replay JSON")
	profileID := flag.String("runtime-profile-id", "", "attested runtime profile")
	gpu := flag.String("gpu-architecture", "", "attested GPU architecture")
	rocm := flag.String("rocm-version", "", "attested ROCm version")
	runtime := flag.String("inference-runtime", "", "attested local inference runtime")
	runtimeRevision := flag.String("runtime-revision", "", "attested runtime revision")
	quantization := flag.String("quantization", "", "attested quantization")
	model := flag.String("model-id", "", "attested source model ID")
	modelRevision := flag.String("model-revision", "", "attested source model revision")
	runtimeEvidenceSHA := flag.String("runtime-evidence-sha", "", "SHA-256 of runtime evidence")
	flag.Parse()

	required := map[string]string{
		"--input": *input, "--output": *output, "--runtime-profile-id": *profileID,
		"--gpu-architecture": *gpu, "--rocm-version": *rocm, "--inference-runtime": *runtime,
		"--runtime-revision": *runtimeRevision, "--quantization": *quantization,
		"--model-id": *model, "--model-revision": *modelRevision,
		"--runtime-evidence-sha": *runtimeEvidenceSHA,
	}
	for name, value := range required {
		if strings.TrimSpace(value) == "" {
			fatal(fmt.Errorf("%s is required", name))
		}
	}
	payload, err := os.ReadFile(*input)
	if err != nil {
		fatal(err)
	}
	var report golden.Report
	if err := json.Unmarshal(payload, &report); err != nil {
		fatal(err)
	}
	replay, err := golden.BuildSafeDecisionReplay(report, golden.RuntimeProfile{
		Attested: true, ProfileID: *profileID, GPUArchitecture: *gpu, ROCmVersion: *rocm,
		Runtime: *runtime, RuntimeRevision: *runtimeRevision, Quantization: *quantization,
		ModelID: *model, ModelRevision: *modelRevision, RuntimeEvidenceSHA: *runtimeEvidenceSHA,
	})
	if err != nil {
		fatal(err)
	}
	payload, err = json.MarshalIndent(replay, "", "  ")
	if err != nil {
		fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(*output), 0o750); err != nil {
		fatal(err)
	}
	if err := os.WriteFile(*output, append(payload, '\n'), 0o640); err != nil {
		fatal(err)
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
