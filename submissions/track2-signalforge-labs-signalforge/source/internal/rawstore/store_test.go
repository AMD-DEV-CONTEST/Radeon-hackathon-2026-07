package rawstore

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestPutCreatesHashAddressedImmutableRecord(t *testing.T) {
	store, err := New(t.TempDir())
	if err != nil {
		t.Fatalf("new store: %v", err)
	}
	content := []byte(`{"cik":"0000789019"}`)
	digest := sha256.Sum256(content)
	hash := hex.EncodeToString(digest[:])
	input := Input{
		SourceURI: "https://data.sec.gov/submissions/CIK0000789019.json",
		MediaType: "application/json", Content: content, ContentSHA: hash,
		RetrievedAt: time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC),
	}
	record, err := store.Put(input)
	if err != nil {
		t.Fatalf("put: %v", err)
	}
	if record.ContentSHA != hash || record.ContentBytes != len(content) {
		t.Fatalf("unexpected record: %+v", record)
	}
	payload, err := os.ReadFile(filepath.Join(store.root, filepath.FromSlash(record.PayloadPath)))
	if err != nil || string(payload) != string(content) {
		t.Fatalf("read payload: %v", err)
	}
	if _, err := store.Put(input); err != nil {
		t.Fatalf("idempotent put failed: %v", err)
	}
	later := input
	later.RetrievedAt = input.RetrievedAt.Add(time.Hour)
	laterRecord, err := store.Put(later)
	if err != nil {
		t.Fatalf("repeat observation failed: %v", err)
	}
	if laterRecord.PayloadPath != record.PayloadPath || laterRecord.RecordPath == record.RecordPath {
		t.Fatalf("expected shared blob and distinct observations: first=%+v later=%+v", record, laterRecord)
	}
}

func TestPutRejectsHashMismatch(t *testing.T) {
	store, _ := New(t.TempDir())
	_, err := store.Put(Input{
		SourceURI: "https://data.sec.gov/example.json", MediaType: "application/json",
		Content: []byte("payload"), ContentSHA: strings.Repeat("0", 64), RetrievedAt: time.Now(),
	})
	if err == nil {
		t.Fatal("hash mismatch must be rejected")
	}
}

func TestSourceURIRedactsCredentials(t *testing.T) {
	store, _ := New(t.TempDir())
	record, err := store.Put(Input{
		SourceURI: "https://user:password@example.com/data?series=GDP&api_key=sensitive&token=also-sensitive#fragment",
		MediaType: "application/json", Content: []byte("payload"), RetrievedAt: time.Now(),
	})
	if err != nil {
		t.Fatalf("put: %v", err)
	}
	for _, secret := range []string{"password", "sensitive", "also-sensitive", "fragment"} {
		if strings.Contains(record.SourceURI, secret) {
			t.Fatalf("source URI leaked %q: %s", secret, record.SourceURI)
		}
	}
	if !strings.Contains(record.SourceURI, "series=GDP") {
		t.Fatalf("non-secret query identity was lost: %s", record.SourceURI)
	}
}

func TestReadPayloadVerifiesStoredContent(t *testing.T) {
	store, err := New(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	record, err := store.Put(Input{
		SourceURI: "https://data.sec.gov/example.json", MediaType: "application/json",
		Content: []byte(`{"ok":true}`), RetrievedAt: time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatal(err)
	}
	content, err := store.ReadPayload(record)
	if err != nil || string(content) != `{"ok":true}` {
		t.Fatalf("content=%q err=%v", content, err)
	}
	record.PayloadPath = "../../outside"
	if _, err := store.ReadPayload(record); err == nil {
		t.Fatal("path traversal must fail")
	}
}
