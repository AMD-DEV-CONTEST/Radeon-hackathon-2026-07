package protocol

import (
	"testing"
	"time"
)

// TestCrossProtocolIntegration tests the full flow across all four protocols:
// Asset → Memory → Spark → Seat, verifying end-to-end integration.
func TestCrossProtocolIntegration(t *testing.T) {
	// ── Setup stores ──────────────────────────────────────────────
	assetStore := NewMemAssetStore()
	memStore := NewMemMemoryStore()
	sparkStore := NewMemSparkStore()
	seatStore := NewMemSeatStore()

	// ── Step 1: Declare seats (Seat Protocol) ─────────────────────
	annivSeat := AnniversaryKeeperSeat()
	memSeat := MemoryKeeperSeat()

	if err := seatStore.Declare(annivSeat); err != nil {
		t.Fatalf("declare anniversary-keeper: %v", err)
	}
	if err := seatStore.Declare(memSeat); err != nil {
		t.Fatalf("declare memory-keeper: %v", err)
	}

	// Verify seats exist
	gotAnniv, err := seatStore.Get("user/anniversary-keeper")
	if err != nil {
		t.Fatalf("get anniversary-keeper: %v", err)
	}
	if !gotAnniv.HasOp(OpVaultRead) {
		t.Error("anniversary-keeper should have vault.read")
	}
	if gotAnniv.HasOp(OpMemorySet) {
		t.Error("anniversary-keeper should NOT have memory.set")
	}

	gotMem, err := seatStore.Get("user/memory-keeper")
	if err != nil {
		t.Fatalf("get memory-keeper: %v", err)
	}
	if !gotMem.HasOp(OpMemorySet) {
		t.Error("memory-keeper should have memory.set")
	}
	if gotMem.HasOp(OpVaultRead) {
		t.Error("memory-keeper should NOT have vault.read")
	}

	// ── Step 2: Authorization checks ──────────────────────────────
	if err := Authorize(seatStore, "user/anniversary-keeper", OpVaultRead); err != nil {
		t.Errorf("anniversary-keeper should be authorized for vault.read: %v", err)
	}
	if err := Authorize(seatStore, "user/anniversary-keeper", OpMemorySet); err == nil {
		t.Error("anniversary-keeper should NOT be authorized for memory.set")
	}
	if err := Authorize(seatStore, "user/memory-keeper", OpMemorySet); err != nil {
		t.Errorf("memory-keeper should be authorized for memory.set: %v", err)
	}
	if err := Authorize(seatStore, "user/nonexistent", OpVaultRead); err == nil {
		t.Error("nonexistent seat should NOT be authorized")
	}

	// ── Step 3: Asset Protocol (vault.read) ───────────────────────
	asset := &AssetLedgerEntry{
		AssetID:     "anniv-2026-06-22",
		AssetType:   AssetCredential,
		Title:       "Wedding Anniversary",
		Owner:       "user/anniversary-keeper",
		ContentHash: "sha256:abc123",
		CreatedAt:   time.Now().UTC(),
		UpdatedAt:   time.Now().UTC(),
	}
	assetStore.Put(asset)

	readAsset, err := assetStore.Read("anniv-2026-06-22")
	if err != nil {
		t.Fatalf("asset read: %v", err)
	}
	if readAsset.Title != "Wedding Anniversary" {
		t.Errorf("expected 'Wedding Anniversary', got '%s'", readAsset.Title)
	}
	if readAsset.Owner != "user/anniversary-keeper" {
		t.Errorf("expected owner 'user/anniversary-keeper', got '%s'", readAsset.Owner)
	}

	// ── Step 4: Memory Protocol (memory.set + memory.get) ─────────
	if err := memStore.Set("life-memory", "anniv-date", "2026-06-22", []string{"anniversary"}); err != nil {
		t.Fatalf("memory set: %v", err)
	}
	if err := memStore.Set("life-memory", "anniv-message", "Happy Anniversary!", []string{"anniversary", "greeting"}); err != nil {
		t.Fatalf("memory set 2: %v", err)
	}

	entry, err := memStore.Get("life-memory", "anniv-date")
	if err != nil {
		t.Fatalf("memory get: %v", err)
	}
	if entry.Value != "2026-06-22" {
		t.Errorf("expected '2026-06-22', got '%s'", entry.Value)
	}
	if len(entry.Tags) != 1 || entry.Tags[0] != "anniversary" {
		t.Errorf("expected tag 'anniversary', got %v", entry.Tags)
	}

	_, err = memStore.Get("life-memory", "nonexistent")
	if err != ErrMemoryNotFound {
		t.Errorf("expected ErrMemoryNotFound, got %v", err)
	}

	// ── Step 5: Spark Protocol (spark.recall) ─────────────────────
	sparkStore.Put(Spark{
		ID:      "spark-001",
		Context: "anniversary-reminder",
		Insight: "Remind user about upcoming anniversary on 2026-06-22",
		Score:   0.95,
	})
	sparkStore.Put(Spark{
		ID:      "spark-002",
		Context: "anniversary-reminder",
		Insight: "Suggest preparing a gift 1 week before",
		Score:   0.80,
	})

	spark, err := sparkStore.Recall("anniversary-reminder")
	if err != nil {
		t.Fatalf("spark recall: %v", err)
	}
	if spark.Insight == "" {
		t.Error("spark insight should not be empty")
	}

	_, err = sparkStore.Recall("unknown-context")
	if err != ErrSparkNotFound {
		t.Errorf("expected ErrSparkNotFound, got %v", err)
	}

	// ── Step 6: Seat enforcement ──────────────────────────────────
	// Simulate a request: anniversary-keeper tries vault.read → allowed
	annivSeat2, _ := seatStore.Get("user/anniversary-keeper")
	if !annivSeat2.HasOp(OpVaultRead) {
		t.Error("anniversary-keeper must have vault.read")
	}

	// anniversary-keeper tries memory.set → denied
	if annivSeat2.HasOp(OpMemorySet) {
		t.Error("anniversary-keeper must NOT have memory.set")
	}

	// memory-keeper tries memory.set → allowed
	memSeat2, _ := seatStore.Get("user/memory-keeper")
	if !memSeat2.HasOp(OpMemorySet) {
		t.Error("memory-keeper must have memory.set")
	}

	t.Log("Cross-protocol integration test passed: Asset→Memory→Spark→Seat→Auth all OK")
}

// TestIndividualProtocols tests each protocol in isolation.
func TestIndividualProtocols(t *testing.T) {
	t.Run("Asset", func(t *testing.T) {
		s := NewMemAssetStore()
		s.Put(&AssetLedgerEntry{AssetID: "a1", Title: "Test Asset", Owner: "test"})

		a, err := s.Read("a1")
		if err != nil {
			t.Fatalf("Read: %v", err)
		}
		if a.Title != "Test Asset" {
			t.Errorf("title: got %s, want Test Asset", a.Title)
		}

		_, err = s.Read("nonexistent")
		if err != ErrAssetNotFound {
			t.Errorf("expected ErrAssetNotFound, got %v", err)
		}
	})

	t.Run("Memory", func(t *testing.T) {
		s := NewMemMemoryStore()
		if err := s.Set("ns", "k1", "v1", nil); err != nil {
			t.Fatalf("Set: %v", err)
		}
		e, err := s.Get("ns", "k1")
		if err != nil {
			t.Fatalf("Get: %v", err)
		}
		if e.Value != "v1" {
			t.Errorf("value: got %s, want v1", e.Value)
		}

		_, err = s.Get("ns", "nonexistent")
		if err != ErrMemoryNotFound {
			t.Errorf("expected ErrMemoryNotFound, got %v", err)
		}
	})

	t.Run("Spark", func(t *testing.T) {
		s := NewMemSparkStore()
		s.Put(Spark{ID: "s1", Context: "ctx", Insight: "test insight"})

		sp, err := s.Recall("ctx")
		if err != nil {
			t.Fatalf("Recall: %v", err)
		}
		if sp.Insight != "test insight" {
			t.Errorf("insight: got %s, want test insight", sp.Insight)
		}

		_, err = s.Recall("unknown")
		if err != ErrSparkNotFound {
			t.Errorf("expected ErrSparkNotFound, got %v", err)
		}
	})

	t.Run("Seat", func(t *testing.T) {
		s := NewMemSeatStore()
		seat := Seat{Name: "user/test", Ops: []Op{OpVaultRead, OpMemoryGet}}
		if err := s.Declare(seat); err != nil {
			t.Fatalf("Declare: %v", err)
		}

		got, err := s.Get("user/test")
		if err != nil {
			t.Fatalf("Get: %v", err)
		}
		if !got.HasOp(OpVaultRead) {
			t.Error("should have vault.read")
		}
		if got.HasOp(OpMemorySet) {
			t.Error("should NOT have memory.set")
		}

		// Duplicate declaration
		if err := s.Declare(seat); err != ErrSeatAlreadyDeclared {
			t.Errorf("expected ErrSeatAlreadyDeclared, got %v", err)
		}
	})
}

func TestAssetLedgerEntryUsesFullLedgerContract(t *testing.T) {
	entry := AssetLedgerEntry{
		AssetID:          "asset-1",
		AssetType:        AssetFamilyArchive,
		ContentHash:      "sha256:abc123",
		Owner:            "user/anniversary-keeper",
		PrivacyLevel:     PrivacyFamily,
		ProcessingStatus: StatusRaw,
		Provenance: Provenance{
			Source:     "test",
			IngestedBy: "protocol-test",
		},
	}

	if entry.PrivacyLevel != PrivacyFamily {
		t.Fatalf("privacy_level=%q, want %q", entry.PrivacyLevel, PrivacyFamily)
	}
	if entry.ProcessingStatus != StatusRaw {
		t.Fatalf("processing_status=%q, want %q", entry.ProcessingStatus, StatusRaw)
	}
}

func TestAssetProtocolAssetTypesMirrorLedgerContract(t *testing.T) {
	got := []AssetType{
		AssetCredential,
		AssetIdentity,
		AssetEducation,
		AssetPolicy,
		AssetTechCredential,
		AssetServicePassword,
		AssetDocument,
		AssetNote,
		AssetHealthRecord,
		AssetFinanceRecord,
		AssetFamilyArchive,
		AssetMemoryNote,
	}

	if len(got) != 12 {
		t.Fatalf("known asset type count=%d, want 12", len(got))
	}
	if got[4] != AssetType("tech-credential") {
		t.Fatalf("tech asset type=%q, want tech-credential", got[4])
	}
	if got[11] != AssetType("memory-note") {
		t.Fatalf("memory asset type=%q, want memory-note", got[11])
	}
}
