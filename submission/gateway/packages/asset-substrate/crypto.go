// Package substrate provides the asset-substrate layer:
// encryption (AES-256-GCM envelope), audit chain (SHA-256 hash chain),
// and PostgreSQL meta store (database/sql CRUD).
package substrate

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
)

// ── Errors ─────────────────────────────────────────────────────────

var (
	ErrInvalidKey     = errors.New("substrate: invalid key size, must be 32 bytes")
	ErrCiphertextTooShort = errors.New("substrate: ciphertext too short")
	ErrDecryptFailed  = errors.New("substrate: decryption failed (bad key or corrupted data)")
)

// ── Constants ───────────────────────────────────────────────────────

const (
	// AESKeySize is the required key length for AES-256.
	AESKeySize = 32
	// NonceSize is the standard GCM nonce length.
	NonceSize = 12
)

// ── Encryption Envelope ─────────────────────────────────────────────

// EncryptedPayload is the serializable envelope returned by Encrypt.
type EncryptedPayload struct {
	// Ciphertext is the base64-encoded AES-256-GCM output (nonce + cipher + tag).
	Ciphertext string `json:"ciphertext"`
	// KeyID is an optional identifier for the key used (not the key itself).
	KeyID string `json:"key_id,omitempty"`
	// Algorithm identifies the encryption scheme.
	Algorithm string `json:"algorithm"`
}

// Encrypt encrypts plaintext with AES-256-GCM and returns a serializable envelope.
// key must be exactly 32 bytes (AES-256).
func Encrypt(plaintext []byte, key []byte, keyID string) (*EncryptedPayload, error) {
	if len(key) != AESKeySize {
		return nil, ErrInvalidKey
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, fmt.Errorf("substrate: aes cipher: %w", err)
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("substrate: gcm: %w", err)
	}

	nonce := make([]byte, NonceSize)
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, fmt.Errorf("substrate: nonce: %w", err)
	}

	// Seal appends the encrypted data (with auth tag) to nonce.
	ciphertext := gcm.Seal(nonce, nonce, plaintext, nil)

	return &EncryptedPayload{
		Ciphertext: base64.StdEncoding.EncodeToString(ciphertext),
		KeyID:      keyID,
		Algorithm:  "AES-256-GCM",
	}, nil
}

// Decrypt decrypts an EncryptedPayload envelope.
// key must match the one used during Encrypt.
func Decrypt(payload *EncryptedPayload, key []byte) ([]byte, error) {
	if len(key) != AESKeySize {
		return nil, ErrInvalidKey
	}

	ciphertext, err := base64.StdEncoding.DecodeString(payload.Ciphertext)
	if err != nil {
		return nil, fmt.Errorf("substrate: base64 decode: %w", err)
	}

	if len(ciphertext) < NonceSize+1 {
		return nil, ErrCiphertextTooShort
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, fmt.Errorf("substrate: aes cipher: %w", err)
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("substrate: gcm: %w", err)
	}

	nonce := ciphertext[:NonceSize]
	sealed := ciphertext[NonceSize:]

	plaintext, err := gcm.Open(nil, nonce, sealed, nil)
	if err != nil {
		return nil, ErrDecryptFailed
	}

	return plaintext, nil
}

// ── Key Derivation Helper ───────────────────────────────────────────

// DeriveKey derives a 32-byte AES-256 key from an arbitrary passphrase using SHA-256.
// This is NOT a proper KDF (use Argon2/PBKDF2 in production). It is sufficient
// for the substrate skeleton's test and dev environments.
func DeriveKey(passphrase string) []byte {
	h := sha256.Sum256([]byte(passphrase))
	return h[:]
}

// ── SHA-256 Hash Helpers ────────────────────────────────────────────

// HashHex returns the hex-encoded SHA-256 digest of data.
func HashHex(data []byte) string {
	h := sha256.Sum256(data)
	return hex.EncodeToString(h[:])
}
