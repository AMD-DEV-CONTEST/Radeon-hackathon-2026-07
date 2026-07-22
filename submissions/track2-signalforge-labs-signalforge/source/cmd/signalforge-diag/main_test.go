package main

import (
	"strings"
	"testing"
	"time"
)

func TestProbeInventoryDoesNotReadEnvironmentOrSecrets(t *testing.T) {
	for _, item := range buildProbes("python3", "/workspace") {
		command := strings.ToLower(strings.Join(append([]string{item.Command}, item.Args...), " "))
		for _, forbidden := range []string{"env", "printenv", "token", "secret", "api_key"} {
			if strings.Contains(command, forbidden) {
				t.Fatalf("probe %q contains forbidden term %q", item.Name, forbidden)
			}
		}
	}
}

func TestProbeInventoryUsesExplicitRuntimePaths(t *testing.T) {
	items := buildProbes("/opt/venv/bin/python", "/workspace/signalforge")
	commands := make(map[string]string, len(items))
	for _, item := range items {
		commands[item.Name] = strings.Join(append([]string{item.Command}, item.Args...), " ")
	}
	if !strings.HasPrefix(commands["pytorch_rocm"], "/opt/venv/bin/python ") {
		t.Fatalf("PyTorch probe did not use explicit Python: %q", commands["pytorch_rocm"])
	}
	if !strings.HasSuffix(commands["workspace_storage"], " /workspace/signalforge") {
		t.Fatalf("storage probe did not use explicit workspace: %q", commands["workspace_storage"])
	}
}

func TestUnavailableProbeFailsClosed(t *testing.T) {
	result := runProbe(probe{Name: "missing", Command: "signalforge-command-that-does-not-exist"}, time.Second)
	if result.Available || result.ExitCode != -1 || result.Error == "" {
		t.Fatalf("unexpected missing-command result: %+v", result)
	}
}
