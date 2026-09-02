package main

import (
	"encoding/json"
	"testing"

	"github.com/rvbernucci/signalforge/internal/capability"
)

func TestBuildCatalogExportsEveryRuntimeMetric(t *testing.T) {
	catalog := buildCatalog()
	if catalog.SchemaVersion != "signalforge.metric-registry/v1" {
		t.Fatalf("schema version = %q", catalog.SchemaVersion)
	}
	if len(catalog.Metrics) != len(capability.RuntimeRegistry().List()) {
		t.Fatalf("catalog metrics = %d, runtime operations = %d", len(catalog.Metrics), len(capability.RuntimeRegistry().List()))
	}
	seen := make(map[string]struct{}, len(catalog.Metrics))
	for _, metric := range catalog.Metrics {
		if _, exists := seen[metric.MetricID]; exists {
			t.Fatalf("duplicate metric %s", metric.MetricID)
		}
		seen[metric.MetricID] = struct{}{}
		if metric.Version == "" || metric.Formula.Expression == "" || metric.Formula.ImplementationOwner == "" {
			t.Fatalf("incomplete governance for %s", metric.MetricID)
		}
		if len(metric.Inputs) == 0 || len(metric.FailureDispositions) == 0 || len(metric.Authority.DefinitionSources) == 0 {
			t.Fatalf("incomplete contract for %s", metric.MetricID)
		}
	}
	if _, err := json.Marshal(catalog); err != nil {
		t.Fatal(err)
	}
}
