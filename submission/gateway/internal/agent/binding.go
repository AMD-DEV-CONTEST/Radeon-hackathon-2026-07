// Package agent defines the Agent Binding Contract — the layer that maps
// agent_type strings to concrete runtimes.
//
// In bridge mode, agent_type is purely metadata — the daemon ignores it
// when ILS_BRIDGE_DIR is set. All subprocess spawn runtimes (reasonix,
// claude_code, codex, opencode) have been removed in favor of bridge mode.
//
// The only remaining runtime is "hermes" — the daemon itself, which handles
// WS/Gateway communication directly.
package agent

import (
	"fmt"
	"os/exec"
	"strings"
	"time"
)

// RuntimeSchema defines how to invoke a specific agent runtime.
type RuntimeSchema struct {
	Type        string            // agent_type key (e.g. "hermes")
	Exe         string            // binary name (empty for remote/non-CLI runtimes)
	ArgTemplate []string          // args; the placeholder "{prompt}" is replaced
	Env         map[string]string // extra env vars injected into the subprocess
	Timeout     time.Duration     // execution timeout
	DoctorCmd   string            // CLI to run for the health check (empty = none)
	DoctorArgs  []string
	RemoteURL   string            // HTTP endpoint for remote runtimes (empty = local CLI)
	ChatPromptWrapper string       // {text} placeholder is replaced with the raw chat message
}

// BindingResult is the outcome of LookupRuntime.
type BindingResult struct {
	OK      bool          // true if the runtime is known and its binary is available
	Runtime RuntimeSchema // the resolved schema (zero-value when !OK)
	ExePath string        // absolute path to the binary (empty for remote runtimes)
	Err     string        // human-readable error when !OK
}

// knownRuntimes is the registry of officially supported agent runtimes.
//
// Only "hermes" remains — all subprocess spawn types (reasonix, claude_code,
// codex, opencode) were removed in v1.0. In bridge mode, the daemon doesn't
// spawn subprocesses regardless of agent_type.
var knownRuntimes = map[string]RuntimeSchema{
	"hermes": {
		Type:       "hermes",
		Exe:        "", // remote agent — no local CLI (daemon handles WS/Gateway directly)
		Timeout:    120 * time.Second,
		DoctorCmd:  "curl",
		DoctorArgs: []string{"-sf", "http://127.0.0.1:8000/health"},
		RemoteURL:  "",
	},
}

// LookupRuntime resolves an agent_type to its RuntimeSchema and verifies the
// binary (if one is declared) exists on PATH.  Returns a structured
// BindingResult — callers must check .OK before using the runtime.
func LookupRuntime(agentType string) BindingResult {
	rt, ok := knownRuntimes[agentType]
	if !ok {
		return BindingResult{
			OK:  false,
			Err: fmt.Sprintf("unknown agent_type %q — must be one of: %s", agentType, knownTypeList()),
		}
	}

	// Remote runtimes (empty Exe) skip the local binary check.
	if rt.Exe != "" {
		path, err := exec.LookPath(rt.Exe)
		if err != nil {
			return BindingResult{
				OK:      false,
				Runtime: rt,
				Err:     fmt.Sprintf("binary %q not found on PATH — install it or check agent_type", rt.Exe),
			}
		}
		rt.Exe = path // store the resolved absolute path
	}

	return BindingResult{OK: true, Runtime: rt, ExePath: rt.Exe}
}

// Doctor runs the runtime's health-check command (e.g. --version).
// Returns nil if the check passes or no check is defined.
func (r RuntimeSchema) Doctor() error {
	if r.DoctorCmd == "" {
		return nil
	}
	cmd := exec.Command(r.DoctorCmd, r.DoctorArgs...)
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("doctor check failed for %s (%s %s): %w",
			r.Type, r.DoctorCmd, strings.Join(r.DoctorArgs, " "), err)
	}
	return nil
}

// BuildArgs substitutes the {prompt} placeholder in the ArgTemplate.
func (r RuntimeSchema) BuildArgs(prompt string) []string {
	args := make([]string, len(r.ArgTemplate))
	for i, a := range r.ArgTemplate {
		args[i] = strings.ReplaceAll(a, "{prompt}", prompt)
	}
	return args
}

// WrapChatPrompt wraps raw chat text for coding agents so they reply concisely
// instead of dumping tool calls, auth flows, and session init logs into OB.
func (r RuntimeSchema) WrapChatPrompt(rawText string) string {
	if r.ChatPromptWrapper == "" {
		return rawText
	}
	return strings.ReplaceAll(r.ChatPromptWrapper, "{text}", rawText)
}

func knownTypeList() string {
	keys := make([]string, 0, len(knownRuntimes))
	for k := range knownRuntimes {
		keys = append(keys, k)
	}
	return strings.Join(keys, ", ")
}