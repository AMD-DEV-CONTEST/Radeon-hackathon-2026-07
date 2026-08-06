package substrate

import (
	"testing"
)

func TestAuditChainAppend(t *testing.T) {
	ac := NewAuditChain()

	e1 := ac.Append("asset.created", "alice", "asset-001", "Created credential asset", nil)
	if e1.Index != 0 {
		t.Errorf("expected index 0, got %d", e1.Index)
	}
	if e1.Hash == "" {
		t.Fatal("hash should not be empty")
	}
	if e1.PrevHash != GenesisHash() {
		t.Errorf("genesis entry should use genesis hash, got %s", e1.PrevHash)
	}
	if !e1.VerifyHash() {
		t.Error("entry hash verification failed")
	}
	if ac.Len() != 1 {
		t.Errorf("expected 1 entry, got %d", ac.Len())
	}
}

func TestAuditChainHashChain(t *testing.T) {
	ac := NewAuditChain()

	ac.Append("asset.created", "alice", "asset-001", "First", nil)
	ac.Append("asset.updated", "bob", "asset-001", "Second", nil)
	ac.Append("asset.deleted", "alice", "asset-001", "Third", nil)

	entries := ac.Entries()
	if len(entries) != 3 {
		t.Fatalf("expected 3 entries, got %d", len(entries))
	}

	// Verify chain linking
	for i := 1; i < len(entries); i++ {
		if entries[i].PrevHash != entries[i-1].Hash {
			t.Errorf("entry %d prev_hash mismatch", i)
		}
	}

	// Verify full chain integrity
	if idx := ac.VerifyChain(); idx != -1 {
		t.Errorf("chain verification failed at index %d", idx)
	}
}

func TestAuditChainTamperEvidence(t *testing.T) {
	ac := NewAuditChain()

	ac.Append("asset.created", "alice", "asset-001", "Original", nil)
	ac.Append("asset.updated", "bob", "asset-001", "Updated", nil)
	ac.Append("asset.deleted", "alice", "asset-001", "Deleted", nil)

	entries := ac.Entries()

	// Tamper with the first entry's summary
	entries[0].Summary = "Tampered!"

	// The tampered entry should fail verification
	if entries[0].VerifyHash() {
		t.Error("tampered entry should NOT verify")
	}

	// Rebuild the chain with tampered data
	ac2 := NewAuditChain()
	for _, e := range entries {
		ac2.entries = append(ac2.entries, e)
	}

	// The first entry fails, but subsequent ones also fail due to chain break
	if idx := ac2.VerifyChain(); idx != 0 {
		t.Errorf("expected tamper detected at index 0, got %d", idx)
	}
}

func TestAuditChainEmpty(t *testing.T) {
	ac := NewAuditChain()

	if ac.Len() != 0 {
		t.Errorf("expected empty chain, got %d entries", ac.Len())
	}
	if last := ac.Last(); last != nil {
		t.Error("expected nil last entry for empty chain")
	}
	if idx := ac.VerifyChain(); idx != -1 {
		t.Errorf("empty chain should be valid, got corruption at %d", idx)
	}
}

func TestAuditChainJSONRoundTrip(t *testing.T) {
	ac := NewAuditChain()

	ac.Append("asset.created", "alice", "asset-001", "JSON test", []byte("opaque"))
	ac.Append("asset.updated", "bob", "asset-002", "Second event", nil)

	data, err := ac.MarshalJSON()
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}

	ac2 := NewAuditChain()
	if err := ac2.UnmarshalJSON(data); err != nil {
		t.Fatalf("unmarshal failed: %v", err)
	}

	if ac2.Len() != ac.Len() {
		t.Errorf("length mismatch: got %d, want %d", ac2.Len(), ac.Len())
	}

	orig := ac.Entries()
	restored := ac2.Entries()
	for i := range orig {
		if orig[i].Hash != restored[i].Hash {
			t.Errorf("entry %d hash mismatch after round-trip", i)
		}
		if orig[i].Index != restored[i].Index {
			t.Errorf("entry %d index mismatch", i)
		}
	}
}

func TestAuditEntryWithData(t *testing.T) {
	ac := NewAuditChain()
	data := []byte(`{"key": "value", "nested": {"a": 1}}`)

	e := ac.Append("custom.event", "system", "target-01", "With payload", data)
	if !e.VerifyHash() {
		t.Error("entry with data should verify")
	}

	if string(e.Data) != string(data) {
		t.Error("data payload mismatch")
	}
}

func TestAuditChainConsecutiveIndices(t *testing.T) {
	ac := NewAuditChain()
	for i := 0; i < 100; i++ {
		ac.Append("test", "tester", "target", "batch test", nil)
	}
	if ac.Len() != 100 {
		t.Errorf("expected 100 entries, got %d", ac.Len())
	}
	if idx := ac.VerifyChain(); idx != -1 {
		t.Errorf("batch chain verification failed at index %d", idx)
	}
	// Verify consecutive indices
	entries := ac.Entries()
	for i := 0; i < len(entries); i++ {
		if entries[i].Index != uint64(i) {
			t.Errorf("entry %d has index %d", i, entries[i].Index)
		}
	}
}
