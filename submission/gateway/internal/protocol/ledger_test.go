package protocol

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestAssetLedgerEntryFixturesMatchSchema(t *testing.T) {
	tests := []struct {
		name  string
		valid bool
	}{
		{name: "valid-entry.json", valid: true},
		{name: "missing-required-field.json", valid: false},
		{name: "bad-hash-format.json", valid: false},
		{name: "bad-privacy-enum.json", valid: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			data := readFixture(t, tt.name)
			result, err := ValidateAssetLedgerEntryJSON(data)
			if err != nil {
				t.Fatalf("validate fixture: %v", err)
			}
			if result.Valid() != tt.valid {
				t.Fatalf("valid=%v, want %v, errors=%v", result.Valid(), tt.valid, result.Errors())
			}
		})
	}
}

func TestAssetLedgerEntryRoundTrip(t *testing.T) {
	data := readFixture(t, "valid-entry.json")
	result, err := ValidateAssetLedgerEntryJSON(data)
	if err != nil {
		t.Fatalf("validate fixture: %v", err)
	}
	if !result.Valid() {
		t.Fatalf("fixture should be valid: %v", result.Errors())
	}

	entry, err := DecodeAssetLedgerEntry(data)
	if err != nil {
		t.Fatalf("decode fixture: %v", err)
	}

	encoded, err := json.Marshal(entry)
	if err != nil {
		t.Fatalf("marshal entry: %v", err)
	}

	roundTripResult, err := ValidateAssetLedgerEntryJSON(encoded)
	if err != nil {
		t.Fatalf("validate round trip: %v", err)
	}
	if !roundTripResult.Valid() {
		t.Fatalf("round trip should be valid: %v", roundTripResult.Errors())
	}
}

func TestKnownAssetTypesMatchTSSourceOfTruth(t *testing.T) {
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
	want := []string{
		"credential",
		"identity",
		"education",
		"policy",
		"tech-credential",
		"service-password",
		"document",
		"note",
		"health-record",
		"finance-record",
		"family-archive",
		"memory-note",
	}

	if len(got) != len(want) {
		t.Fatalf("known asset type count=%d, want %d", len(got), len(want))
	}
	for i := range want {
		if string(got[i]) != want[i] {
			t.Fatalf("asset type[%d]=%q, want %q", i, got[i], want[i])
		}
	}
}

func TestEmbeddedSchemaMatchesSourceWhenAvailable(t *testing.T) {
	source := os.Getenv("OMIMA_LEDGER_SCHEMA")
	if source == "" {
		source = "D:/OMIMA/packages/protocol/src/ledger/schema.json"
	}

	data, err := os.ReadFile(source)
	if errors.Is(err, os.ErrNotExist) {
		t.Skipf("source schema unavailable: %s", source)
	}
	if err != nil {
		t.Fatalf("read source schema: %v", err)
	}
	if !bytes.Equal(bytes.TrimSpace(assetLedgerEntrySchema), bytes.TrimSpace(data)) {
		t.Fatalf("embedded schema differs from source schema %s; run go generate ./internal/protocol", source)
	}
}

func readFixture(t *testing.T, name string) []byte {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("testdata", "fixtures", name))
	if err != nil {
		t.Fatalf("read fixture %s: %v", name, err)
	}
	return data
}
