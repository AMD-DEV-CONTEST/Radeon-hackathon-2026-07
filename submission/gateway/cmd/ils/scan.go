package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

type ToolInfo struct {
	Name    string `json:"name"`
	Binary  string `json:"binary"`
	Path    string `json:"path,omitempty"`
	Version string `json:"version,omitempty"`
	Found   bool   `json:"found"`
}

type ScanResult struct {
	Hostname string     `json:"hostname"`
	OS       string     `json:"os"`
	Arch     string     `json:"arch"`
	Tools    []ToolInfo `json:"tools"`
}

var toolDefs = []struct {
	name    string
	bin     string
	verFlag string
}{
	{"python3", "python3", "--version"},
	{"python", "python", "--version"},
	{"node", "node", "--version"},
	{"npm", "npm", "--version"},
	{"go", "go", "version"},
	{"rustc", "rustc", "--version"},
	{"cargo", "cargo", "--version"},
	{"gcc", "gcc", "--version"},
	{"make", "make", "--version"},
	{"git", "git", "--version"},
	{"docker", "docker", "--version"},
	{"psql", "psql", "--version"},
	{"claude-code", "claude", "--version"},
	{"hermes", "hermes", "--version"},
	{"opencode", "opencode", "--version"},
	{"codex", "codex", "--version"},
	{"reasonix", "reasonix", "--version"},
	{"goose", "goose", "--version"},
	{"cursor-agent", "cursor-agent", "--version"},
}

func RunScan() *ScanResult {
	result := &ScanResult{
		Hostname: getHostname(),
		OS:       runtime.GOOS,
		Arch:     runtime.GOARCH,
		Tools:    make([]ToolInfo, 0, len(toolDefs)),
	}

	for _, td := range toolDefs {
		ti := ToolInfo{Name: td.name, Binary: td.bin, Found: false}

		path, err := exec.LookPath(td.bin)
		if err != nil {
			result.Tools = append(result.Tools, ti)
			continue
		}

		ti.Found = true
		ti.Path = path
		ti.Version = probeVersion(path, td.verFlag)
		result.Tools = append(result.Tools, ti)
	}

	return result
}

func probeVersion(binPath, verFlag string) string {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	args := strings.Fields(verFlag)
	cmd := exec.CommandContext(ctx, binPath, args...)
	out, err := cmd.Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

func getHostname() string {
	out, err := exec.Command("hostname").Output()
	if err != nil {
		return "unknown"
	}
	return strings.TrimSpace(string(out))
}

func scanPretty(r *ScanResult) {
	fmt.Printf("Host: %s  OS: %s/%s\n\n", r.Hostname, r.OS, r.Arch)
	for _, t := range r.Tools {
		if t.Found {
			s := fmt.Sprintf("  ✅ %-14s %s", t.Name, t.Path)
			if t.Version != "" {
				s += fmt.Sprintf("  (%s)", t.Version)
			}
			fmt.Println(s)
		} else {
			fmt.Printf("  ❌ %-14s (not found)\n", t.Name)
		}
	}
	found := 0
	for _, t := range r.Tools {
		if t.Found {
			found++
		}
	}
	fmt.Printf("\n%d/%d tools found\n", found, len(r.Tools))
}

func ilsScan(args []string) {
	jsonOut := false
	for _, a := range args {
		if a == "--json" {
			jsonOut = true
			break
		}
	}
	r := RunScan()
	if jsonOut {
		b, _ := json.MarshalIndent(r, "", "  ")
		fmt.Println(string(b))
	} else {
		scanPretty(r)
	}
}
