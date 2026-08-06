// Package protocol provides the minimal op subsets for the four protocols:
// Asset, Memory, Spark, and Seat.
package protocol

import (
	"errors"

	ledger "github.com/konspace/unionagents-go/internal/protocol"
)

// ── Asset Protocol ──────────────────────────────────────────────────
//
// Asset Protocol defines the vault.read operation: retrieving an asset
// ledger entry by its ID.

type AssetType = ledger.AssetType

const (
	AssetCredential      = ledger.AssetCredential
	AssetIdentity        = ledger.AssetIdentity
	AssetEducation       = ledger.AssetEducation
	AssetPolicy          = ledger.AssetPolicy
	AssetTechCredential  = ledger.AssetTechCredential
	AssetServicePassword = ledger.AssetServicePassword
	AssetDocument        = ledger.AssetDocument
	AssetNote            = ledger.AssetNote
	AssetHealthRecord    = ledger.AssetHealthRecord
	AssetFinanceRecord   = ledger.AssetFinanceRecord
	AssetFamilyArchive   = ledger.AssetFamilyArchive
	AssetMemoryNote      = ledger.AssetMemoryNote
)

type PrivacyLevel = ledger.PrivacyLevel

const (
	PrivacyPrivate = ledger.PrivacyPrivate
	PrivacyFamily  = ledger.PrivacyFamily
	PrivacyPublic  = ledger.PrivacyPublic
)

type ProcessingStatus = ledger.ProcessingStatus

const (
	StatusRaw      = ledger.StatusRaw
	StatusStaging  = ledger.StatusStaging
	StatusDerived  = ledger.StatusDerived
	StatusArchived = ledger.StatusArchived
)

type Provenance = ledger.Provenance

// AssetLedgerEntry aliases the full ledger contract shared with internal/protocol.
type AssetLedgerEntry = ledger.AssetLedgerEntry

// AssetStore is the interface for vault.read.
type AssetStore interface {
	Read(assetID string) (*AssetLedgerEntry, error)
}

// ── Errors ─────────────────────────────────────────────────────────

var (
	ErrAssetNotFound = errors.New("protocol: asset not found")
)

// ── In-Memory Asset Store ───────────────────────────────────────────

// MemAssetStore is an in-memory implementation for testing.
type MemAssetStore struct {
	assets map[string]*AssetLedgerEntry
}

func NewMemAssetStore() *MemAssetStore {
	return &MemAssetStore{assets: make(map[string]*AssetLedgerEntry)}
}

func (s *MemAssetStore) Read(assetID string) (*AssetLedgerEntry, error) {
	a, ok := s.assets[assetID]
	if !ok {
		return nil, ErrAssetNotFound
	}
	return a, nil
}

func (s *MemAssetStore) Put(entry *AssetLedgerEntry) {
	s.assets[entry.AssetID] = entry
}
