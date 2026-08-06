package main

import (
	"testing"
)

func TestResolveFromProfileFillsAgentID(t *testing.T) {
	newProfileStoreDir(t)
	_ = profileSet(Profile{Name: "x1", AgentID: "x1-agent"})

	got, err := resolveFromProfile("x1", "", "")
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	if got.fromAgentID != "x1-agent" {
		t.Fatalf("fromAgentID: got %q want x1-agent", got.fromAgentID)
	}
	if got.from == "" {
		t.Fatal("from should be non-empty (default display name)")
	}
}

func TestResolveFromAgentIDOverridesProfile(t *testing.T) {
	newProfileStoreDir(t)
	_ = profileSet(Profile{Name: "x1", AgentID: "x1-agent"})

	// Explicit --from-agent-id wins over --from-profile.
	got, err := resolveFromProfile("x1", "explicit-id", "")
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	if got.fromAgentID != "explicit-id" {
		t.Fatalf("fromAgentID: got %q want explicit-id", got.fromAgentID)
	}
}

func TestResolveFromProfileMissingErrors(t *testing.T) {
	newProfileStoreDir(t)
	_, err := resolveFromProfile("nope", "", "")
	if err == nil {
		t.Fatal("missing profile should error")
	}
}

func TestResolveFromProfileNotCalledWhenNoProfile(t *testing.T) {
	// Without --from-profile, when --from-agent-id is also empty, returns
	// zero identity (caller applies existing defaults).
	got, err := resolveFromProfile("", "", "")
	if err != nil {
		t.Fatalf("resolve with nothing: %v", err)
	}
	if got.fromAgentID != "" || got.from != "" {
		t.Fatalf("expected zero identity, got %+v", got)
	}
}
