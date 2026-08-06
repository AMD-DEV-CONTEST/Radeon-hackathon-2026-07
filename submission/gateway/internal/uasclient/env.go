package uasclient

import (
	"io"
	"os"
	"path/filepath"
	"strconv"
	"time"
)

// envOr returns the env var key's value, or fallback if unset/empty.
func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// envSeconds parses key as a positive integer number of seconds,
// returning fallback on any error or non-positive value.
func envSeconds(key string, fallback int) time.Duration {
	raw := os.Getenv(key)
	if raw == "" {
		return time.Duration(fallback)
	}
	n, err := strconv.Atoi(raw)
	if err != nil || n <= 0 {
		return time.Duration(fallback)
	}
	return time.Duration(n)
}

// envBool treats "1", "true", "yes", "on" (case-insensitive) as true.
// Anything else (including empty) is false.
func envBool(key string) bool {
	switch os.Getenv(key) {
	case "1", "true", "TRUE", "True", "yes", "YES", "on", "ON":
		return true
	}
	return false
}

// resolveWorkspace picks a default directory for dedupe + cursor
// persistence. Order of preference:
//
//  1. Config.Workspace if non-empty
//  2. $UASCLIENT_HOME
//  3. $XDG_DATA_HOME/unionagents/uasclient
//  4. %APPDATA%\unionagents\uasclient (Windows)
//  5. $HOME/.local/share/unionagents/uasclient (POSIX)
//
// The returned path is NOT created. The caller is responsible for
// MkdirAll at first write, and for tolerating failure (a missing
// workspace degrades the client to in-memory dedupe + no replay
// cursor, which is fine for ephemeral use).
func resolveWorkspace(cfg Config) string {
	if cfg.Workspace != "" {
		return cfg.Workspace
	}
	if v := os.Getenv("UASCLIENT_HOME"); v != "" {
		return v
	}
	if v := os.Getenv("XDG_DATA_HOME"); v != "" {
		return filepath.Join(v, "unionagents", "uasclient")
	}
	if v := os.Getenv("APPDATA"); v != "" {
		return filepath.Join(v, "unionagents", "uasclient")
	}
	if v := os.Getenv("HOME"); v != "" {
		return filepath.Join(v, ".local", "share", "unionagents", "uasclient")
	}
	return ""
}

// resolveStderr picks the default stderr writer.
func resolveStderr(cfg Config) io.Writer {
	if cfg.Stderr != nil {
		return cfg.Stderr
	}
	return os.Stderr
}
