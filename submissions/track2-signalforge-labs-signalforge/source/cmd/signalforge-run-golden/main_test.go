package main

import (
	"strings"
	"testing"
)

func TestRuntimeProfileRequiresCompleteAttestation(t *testing.T) {
	t.Parallel()
	if _, err := runtimeProfile(runtimeProfileInput{ProfileID: "partial"}, "local-model"); err == nil {
		t.Fatal("partial runtime attestation must fail closed")
	}
	profile, err := runtimeProfile(runtimeProfileInput{
		ProfileID: "radeon", GPUArchitecture: "gfx1100", ROCmVersion: "7.2.1",
		Runtime: "llama.cpp", RuntimeRevision: "runtime-revision", Quantization: "QAT-Q4_0",
		ModelRevision: "model-revision", RuntimeEvidenceSHA: strings.Repeat("a", 64),
	}, "local-model")
	if err != nil {
		t.Fatal(err)
	}
	if !profile.Attested || profile.ModelID != "local-model" {
		t.Fatalf("unexpected complete runtime profile: %+v", profile)
	}
}

func TestRuntimeProfileAllowsExplicitlyUnattestedLocalReplay(t *testing.T) {
	t.Parallel()
	profile, err := runtimeProfile(runtimeProfileInput{}, "local-model")
	if err != nil {
		t.Fatal(err)
	}
	if profile.Attested || profile.ModelID != "local-model" {
		t.Fatalf("unexpected unattested profile: %+v", profile)
	}
}
