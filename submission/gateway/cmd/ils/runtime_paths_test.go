package main

import (
	"path/filepath"
	"runtime"
	"testing"
)

func TestILSHomeDefault(t *testing.T) {
	t.Setenv("ILS_HOME", "")
	dir := ilsHome()
	if dir == "" {
		t.Fatal("ilsHome returned empty")
	}
	// Windows: %APPDATA%\unionagents\ils ; POSIX: $XDG_DATA_HOME/.../ils
	if runtime.GOOS == "windows" {
		if !filepath.IsAbs(dir) {
			t.Fatalf("ilsHome not absolute on windows: %q", dir)
		}
	}
}

func TestILSHomeOverride(t *testing.T) {
	t.Setenv("ILS_HOME", "/tmp/ils-test-home")
	if got := ilsHome(); got != "/tmp/ils-test-home" {
		t.Fatalf("ilsHome override: got %q want /tmp/ils-test-home", got)
	}
}

func TestRuntimeBaseUsesILSRuntimeHome(t *testing.T) {
	t.Setenv("ILS_RUNTIME_HOME", "/tmp/ils-rt")
	if got := runtimeBase("/tmp/ils-home"); got != "/tmp/ils-rt" {
		t.Fatalf("runtimeBase: got %q want /tmp/ils-rt", got)
	}
}

func TestRuntimeBaseFallsBackToILSHome(t *testing.T) {
	t.Setenv("ILS_RUNTIME_HOME", "")
	if got := runtimeBase("/tmp/ils-home"); got != "/tmp/ils-home" {
		t.Fatalf("runtimeBase fallback: got %q want /tmp/ils-home", got)
	}
}

func TestProfileRuntimePaths(t *testing.T) {
	pp := profilePaths("/tmp/rt", "x1")
	if pp.inbox != filepath.Join("/tmp/rt", "runtime", "agents", "x1", "inbox.ndjson") {
		t.Fatalf("inbox path: got %q", pp.inbox)
	}
	if pp.state != filepath.Join("/tmp/rt", "runtime", "agents", "x1", "state") {
		t.Fatalf("state path: got %q", pp.state)
	}
	if pp.log != filepath.Join("/tmp/rt", "runtime", "agents", "x1", "daemon.log") {
		t.Fatalf("log path: got %q", pp.log)
	}
	if pp.uasclientWorkspace != filepath.Join("/tmp/rt", "runtime", "agents", "x1", "uasclient") {
		t.Fatalf("uasclient workspace: got %q", pp.uasclientWorkspace)
	}
	if pp.lockFile != filepath.Join("/tmp/rt", "runtime", "agents", "x1", "daemon.lock") {
		t.Fatalf("lock path: got %q", pp.lockFile)
	}
}
