package main

import (
	"path/filepath"
	"testing"
	"time"
)

func TestEvaluateFixtureWorkspace(t *testing.T) {
	root := filepath.Join("..", "..")
	result, err := evaluate(
		filepath.Join(root, "fixtures", "workspace", "golden-case.json"),
		filepath.Join(root, "web", "dist"), time.Millisecond,
	)
	if err != nil {
		t.Fatal(err)
	}
	if result.Frontend.IndexStatus != 200 || !result.Frontend.ContentSecurityReady {
		t.Fatalf("frontend = %+v", result.Frontend)
	}
	if result.Journey.StartStatus != 202 || result.Journey.StreamedEvents == 0 || result.Journey.Sections != 8 || !result.Journey.PrivateFieldsExcluded {
		t.Fatalf("journey = %+v", result.Journey)
	}
}
