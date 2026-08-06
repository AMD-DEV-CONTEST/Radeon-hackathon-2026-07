package substrate

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"time"
)

// ── Audit Chain ─────────────────────────────────────────────────────
//
// AuditChain is an append-only event log where each entry is linked to
// the previous entry via a SHA-256 hash chain. This provides tamper
// evidence: changing any entry invalidates all subsequent hashes.

// AuditEntry is a single entry in the audit chain.
type AuditEntry struct {
	Index     uint64    `json:"index"`     // monotonically increasing
	Timestamp time.Time `json:"timestamp"` // when the event occurred
	EventType string    `json:"event_type"`
	Actor     string    `json:"actor"`
	Target    string    `json:"target,omitempty"`
	Summary   string    `json:"summary"`
	PrevHash  string    `json:"prev_hash"` // SHA-256 of the previous entry (hex)
	Hash      string    `json:"hash"`      // SHA-256 of this entry (hex)
	Data      []byte    `json:"data,omitempty"` // optional opaque payload
}

// ComputeHash computes the SHA-256 hash of the entry's content.
// The hash covers all fields EXCEPT the Hash field itself (to avoid circularity).
func (e *AuditEntry) ComputeHash() string {
	h := sha256.New()
	_, _ = fmt.Fprintf(h, "%d", e.Index)
	_, _ = fmt.Fprintf(h, "%s", e.Timestamp.Format(time.RFC3339Nano))
	_, _ = fmt.Fprintf(h, "%s", e.EventType)
	_, _ = fmt.Fprintf(h, "%s", e.Actor)
	_, _ = fmt.Fprintf(h, "%s", e.Target)
	_, _ = fmt.Fprintf(h, "%s", e.Summary)
	_, _ = fmt.Fprintf(h, "%s", e.PrevHash)
	if e.Data != nil {
		h.Write(e.Data)
	}
	return hex.EncodeToString(h.Sum(nil))
}

// VerifyHash checks whether the stored Hash matches the recomputed hash.
func (e *AuditEntry) VerifyHash() bool {
	return e.Hash == e.ComputeHash()
}

// AuditChain represents an in-memory append-only audit chain.
// For production use, entries are persisted in PostgreSQL (see pgmeta.go).
type AuditChain struct {
	entries []AuditEntry
}

// NewAuditChain creates a new empty audit chain.
func NewAuditChain() *AuditChain {
	return &AuditChain{entries: make([]AuditEntry, 0)}
}

// Append adds a new entry to the chain and returns it.
// If the chain is empty, prev_hash is the zero hash.
// The entry's hash is computed automatically.
func (ac *AuditChain) Append(eventType, actor, target, summary string, data []byte) AuditEntry {
	var prevHash string
	if len(ac.entries) > 0 {
		prevHash = ac.entries[len(ac.entries)-1].Hash
	} else {
		// Genesis: hash of empty string
		h := sha256.Sum256([]byte{})
		prevHash = hex.EncodeToString(h[:])
	}

	entry := AuditEntry{
		Index:     uint64(len(ac.entries)),
		Timestamp: time.Now().UTC(),
		EventType: eventType,
		Actor:     actor,
		Target:    target,
		Summary:   summary,
		PrevHash:  prevHash,
		Data:      data,
	}
	entry.Hash = entry.ComputeHash()
	ac.entries = append(ac.entries, entry)
	return entry
}

// Entries returns a copy of all entries in the chain.
func (ac *AuditChain) Entries() []AuditEntry {
	result := make([]AuditEntry, len(ac.entries))
	copy(result, ac.entries)
	return result
}

// Last returns the most recent entry, or nil if the chain is empty.
func (ac *AuditChain) Last() *AuditEntry {
	if len(ac.entries) == 0 {
		return nil
	}
	return &ac.entries[len(ac.entries)-1]
}

// VerifyChain verifies the integrity of the entire chain.
// Returns the index of the first corrupted entry, or -1 if the chain is valid.
func (ac *AuditChain) VerifyChain() int {
	for i, e := range ac.entries {
		if !e.VerifyHash() {
			return i
		}
		if i > 0 {
			if e.PrevHash != ac.entries[i-1].Hash {
				return i
			}
		}
	}
	return -1
}

// Len returns the number of entries in the chain.
func (ac *AuditChain) Len() int {
	return len(ac.entries)
}

// ── Serialization ───────────────────────────────────────────────────

// MarshalJSON serializes the entire chain as JSON.
func (ac *AuditChain) MarshalJSON() ([]byte, error) {
	return json.Marshal(ac.entries)
}

// UnmarshalJSON deserializes a JSON array into the chain.
func (ac *AuditChain) UnmarshalJSON(data []byte) error {
	var entries []AuditEntry
	if err := json.Unmarshal(data, &entries); err != nil {
		return err
	}
	ac.entries = entries
	return nil
}

// ── Genesis Hash ────────────────────────────────────────────────────

// GenesisHash returns the hash of an empty string, used as the first prev_hash.
func GenesisHash() string {
	h := sha256.Sum256([]byte{})
	return hex.EncodeToString(h[:])
}
