package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/productscope"
)

func TestDevelopmentPeerPreflightPassesAllFortyCases(t *testing.T) {
	root := filepath.Join("..", "..")
	var suite productscope.PeerJourneySuite
	load(t, filepath.Join(root, "fixtures", "productscope", "technology20-peer-development.json"), &suite)
	var catalog productscope.PublicCatalog
	load(t, filepath.Join(root, "fixtures", "productscope", "technology20-catalog.json"), &catalog)
	var peers productscope.PeerEvaluationSuite
	load(t, filepath.Join(root, "fixtures", "productscope", "technology20-peer-evaluation.json"), &peers)
	result := evaluate(suite, catalog, peers, time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC))
	if !result.Passed || result.DispositionPassed != 40 {
		t.Fatalf("preflight = %+v", result)
	}
}

func load(t *testing.T, path string, target any) {
	t.Helper()
	payload, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(payload, target); err != nil {
		t.Fatal(err)
	}
}
