package casestore

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/workspace"
)

func TestStoreRoundTripExportAndSecureDelete(t *testing.T) {
	path := filepath.Join(t.TempDir(), "private", "cases.db")
	store, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	store.now = func() time.Time { return time.Date(2026, 7, 22, 6, 0, 0, 0, time.UTC) }
	projection := loadProjection(t)
	if err := store.Save(context.Background(), projection, "parent-run"); err != nil {
		t.Fatal(err)
	}
	if err := store.Save(context.Background(), projection, "parent-run"); !errors.Is(err, ErrConflict) {
		t.Fatalf("duplicate save error = %v", err)
	}

	loaded, summary, err := store.Get(context.Background(), projection.CaseID)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.RunID != projection.RunID || summary.ParentRunID != "parent-run" || summary.EvidenceItems != len(projection.Evidence) {
		t.Fatalf("loaded = %+v, summary = %+v", loaded, summary)
	}
	items, err := store.List(context.Background(), 10)
	if err != nil || len(items) != 1 {
		t.Fatalf("items = %+v, err = %v", items, err)
	}
	exported, err := store.Export(context.Background(), projection.CaseID)
	if err != nil || exported.SchemaVersion != workspace.CaseExportSchemaV1 || exported.Case.CaseID != projection.CaseID {
		t.Fatalf("export = %+v, err = %v", exported, err)
	}
	payload, _ := json.Marshal(exported)
	for _, forbidden := range []string{"prompt_body", "response_body", "chain_of_thought", "api_key"} {
		if strings.Contains(strings.ToLower(string(payload)), forbidden) {
			t.Fatalf("export leaked %q", forbidden)
		}
	}
	if err := store.Delete(context.Background(), projection.CaseID); err != nil {
		t.Fatal(err)
	}
	if _, _, err := store.Get(context.Background(), projection.CaseID); !errors.Is(err, ErrNotFound) {
		t.Fatalf("deleted case error = %v", err)
	}
	if err := store.Delete(context.Background(), projection.CaseID); !errors.Is(err, ErrNotFound) {
		t.Fatalf("second delete error = %v", err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("database permissions = %o", info.Mode().Perm())
	}
}

func TestStoreRejectsInvalidProjection(t *testing.T) {
	store, err := Open(":memory:")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	projection := loadProjection(t)
	projection.Execution.LocalOnly = false
	if err := store.Save(context.Background(), projection, ""); err == nil {
		t.Fatal("expected invalid projection to be rejected")
	}
}

func TestOpenNeverChangesPermissionsOfExistingParentDirectory(t *testing.T) {
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o755); err != nil {
		t.Fatal(err)
	}
	store, err := Open(filepath.Join(directory, "cases.db"))
	if err != nil {
		t.Fatal(err)
	}
	store.Close()
	info, err := os.Stat(directory)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o755 {
		t.Fatalf("existing parent permissions changed to %o", info.Mode().Perm())
	}
}

func TestStoreRejectsCredentialShapedValuesWithoutPersistingThem(t *testing.T) {
	store, err := Open(":memory:")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	projection := loadProjection(t)
	projection.Question = "Compare the companies with api_key=super-secret-value"
	if err := store.Save(context.Background(), projection, ""); err == nil || strings.Contains(err.Error(), "super-secret-value") {
		t.Fatalf("credential-shaped value was not rejected safely: %v", err)
	}
	items, err := store.List(context.Background(), 10)
	if err != nil || len(items) != 0 {
		t.Fatalf("credential-shaped case reached storage: items=%d err=%v", len(items), err)
	}
}

func loadProjection(t *testing.T) workspace.Projection {
	t.Helper()
	payload, err := os.ReadFile(filepath.Join("..", "..", "fixtures", "workspace", "golden-case.json"))
	if err != nil {
		t.Fatal(err)
	}
	var projection workspace.Projection
	if err := json.Unmarshal(payload, &projection); err != nil {
		t.Fatal(err)
	}
	return projection
}
