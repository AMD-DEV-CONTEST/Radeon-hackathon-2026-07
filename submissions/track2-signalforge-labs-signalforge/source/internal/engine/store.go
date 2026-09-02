package engine

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

var shaPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)

type ReceiptStore struct {
	root string
}

type Supersession struct {
	SchemaVersion         string    `json:"schema_version"`
	PriorReceiptSHA       string    `json:"prior_receipt_sha256"`
	ReplacementReceiptSHA string    `json:"replacement_receipt_sha256"`
	Reason                string    `json:"reason"`
	CreatedAt             time.Time `json:"created_at"`
}

func NewReceiptStore(root string) (*ReceiptStore, error) {
	if root == "" {
		return nil, errors.New("receipt store root is required")
	}
	absolute, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	return &ReceiptStore{root: absolute}, nil
}

func VerifyReceipt(receipt contracts.CalculationReceipt) error {
	if err := contracts.ValidateCalculationReceipt(receipt); err != nil {
		return err
	}
	digest, err := receiptDigest(receipt)
	if err != nil {
		return err
	}
	if digest != receipt.ReceiptSHA {
		return errors.New("receipt hash does not match canonical content")
	}
	return nil
}

func (store *ReceiptStore) Save(receipt contracts.CalculationReceipt) (string, error) {
	if err := VerifyReceipt(receipt); err != nil {
		return "", err
	}
	encoded, err := json.MarshalIndent(receipt, "", "  ")
	if err != nil {
		return "", err
	}
	encoded = append(encoded, '\n')
	path := store.receiptPath(receipt.ReceiptSHA)
	if existing, err := os.ReadFile(path); err == nil {
		if !bytes.Equal(existing, encoded) {
			return "", errors.New("immutable receipt hash already contains different bytes")
		}
		return path, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return "", err
	}
	temporary, err := os.CreateTemp(filepath.Dir(path), ".receipt-*")
	if err != nil {
		return "", err
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if err := temporary.Chmod(0o640); err != nil {
		temporary.Close()
		return "", err
	}
	if _, err := temporary.Write(encoded); err != nil {
		temporary.Close()
		return "", err
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return "", err
	}
	if err := temporary.Close(); err != nil {
		return "", err
	}
	if err := os.Rename(temporaryPath, path); err != nil {
		return "", err
	}
	return path, nil
}

func (store *ReceiptStore) Load(receiptSHA string) (contracts.CalculationReceipt, error) {
	if !shaPattern.MatchString(receiptSHA) {
		return contracts.CalculationReceipt{}, errors.New("invalid receipt hash")
	}
	encoded, err := os.ReadFile(store.receiptPath(receiptSHA))
	if err != nil {
		return contracts.CalculationReceipt{}, err
	}
	var receipt contracts.CalculationReceipt
	if err := json.Unmarshal(encoded, &receipt); err != nil {
		return contracts.CalculationReceipt{}, err
	}
	if receipt.ReceiptSHA != receiptSHA {
		return contracts.CalculationReceipt{}, errors.New("receipt path and content hash differ")
	}
	if err := VerifyReceipt(receipt); err != nil {
		return contracts.CalculationReceipt{}, err
	}
	return receipt, nil
}

func (store *ReceiptStore) Supersede(priorSHA, replacementSHA, reason string, createdAt time.Time) (string, error) {
	if reason == "" || createdAt.IsZero() {
		return "", errors.New("supersession reason and created_at are required")
	}
	if priorSHA == replacementSHA {
		return "", errors.New("a receipt cannot supersede itself")
	}
	if _, err := store.Load(priorSHA); err != nil {
		return "", fmt.Errorf("load prior receipt: %w", err)
	}
	if _, err := store.Load(replacementSHA); err != nil {
		return "", fmt.Errorf("load replacement receipt: %w", err)
	}
	record := Supersession{SchemaVersion: "signalforge/receipt-supersession/v1", PriorReceiptSHA: priorSHA, ReplacementReceiptSHA: replacementSHA, Reason: reason, CreatedAt: createdAt.UTC()}
	encoded, err := json.MarshalIndent(record, "", "  ")
	if err != nil {
		return "", err
	}
	encoded = append(encoded, '\n')
	path := filepath.Join(store.root, "supersessions", replacementSHA+".json")
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return "", err
	}
	if existing, err := os.ReadFile(path); err == nil {
		if !bytes.Equal(existing, encoded) {
			return "", errors.New("replacement receipt already has a different supersession record")
		}
		return path, nil
	}
	if err := os.WriteFile(path, encoded, 0o640); err != nil {
		return "", err
	}
	return path, nil
}

func (store *ReceiptStore) receiptPath(receiptSHA string) string {
	return filepath.Join(store.root, "receipts", receiptSHA[:2], receiptSHA+".json")
}
