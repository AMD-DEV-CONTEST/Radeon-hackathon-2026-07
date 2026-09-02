package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/rvbernucci/signalforge/internal/localagent"
	"github.com/rvbernucci/signalforge/internal/roles"
)

type manifest struct {
	SchemaVersion string              `json:"schema_version"`
	PromptSet     string              `json:"prompt_set"`
	Prompts       []localagent.Prompt `json:"prompts"`
}

func main() {
	registry := localagent.DefaultPromptRegistry()
	if err := registry.Validate(roles.DefaultRegistry()); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	payload, err := json.MarshalIndent(manifest{
		SchemaVersion: "signalforge/role-prompt-manifest/v1",
		PromptSet:     localagent.PromptSetVersion,
		Prompts:       registry.List(),
	}, "", "  ")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	fmt.Println(string(payload))
}
