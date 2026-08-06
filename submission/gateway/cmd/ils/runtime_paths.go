package main

import (
	"os"
	"path/filepath"
)

// profileRuntimePaths is the resolved per-profile file/directory layout.
// Every field is an absolute path (except zero-value overrides).
type profileRuntimePaths struct {
	inbox              string // inbox.ndjson
	state              string // state dir (ILS-owned, NOT uasclient)
	log                string // daemon.log
	uasclientWorkspace string // dir for uasclient dedupe+cursor (seen/, cursor/)
	lockFile           string // daemon.lock
}

// ilsHome returns the ILS config + (default) runtime home.
// Windows: %APPDATA%\unionagents\ils ; POSIX: $XDG_DATA_HOME/unionagents/ils
// (falls back to ~/.local/share/unionagents/ils). Override: ILS_HOME env.
//
// Mirrors the precedence in internal/uasclient/env.go resolveWorkspace
// (APPDATA before XDG before HOME) so Windows and POSIX both land in a
// stable, machine-wide location rather than a CWD-relative one.
func ilsHome() string {
	if v := os.Getenv("ILS_HOME"); v != "" {
		return v
	}
	if v := os.Getenv("APPDATA"); v != "" {
		return filepath.Join(v, "unionagents", "ils")
	}
	if v := os.Getenv("XDG_DATA_HOME"); v != "" {
		return filepath.Join(v, "unionagents", "ils")
	}
	if v := os.Getenv("HOME"); v != "" {
		return filepath.Join(v, ".local", "share", "unionagents", "ils")
	}
	return ""
}

// runtimeBase returns the runtime tree root. Precedence:
//  1. ILS_RUNTIME_HOME env
//  2. the caller-supplied fallback (ilsHome() or a --base flag value)
//
// Keeping ILS_HOME (config + default runtime) separate from
// ILS_RUNTIME_HOME (runtime-only override) lets config live in a stable
// APPDATA home while runtime can be redirected into a repo for
// acceptance-path matching.
func runtimeBase(fallback string) string {
	if v := os.Getenv("ILS_RUNTIME_HOME"); v != "" {
		return v
	}
	return fallback
}

// profilePaths resolves the per-profile runtime layout under base.
func profilePaths(base, profile string) profileRuntimePaths {
	root := filepath.Join(base, "runtime", "agents", profile)
	return profileRuntimePaths{
		inbox:              filepath.Join(root, "inbox.ndjson"),
		state:              filepath.Join(root, "state"),
		log:                filepath.Join(root, "daemon.log"),
		uasclientWorkspace: filepath.Join(root, "uasclient"),
		lockFile:           filepath.Join(root, "daemon.lock"),
	}
}
