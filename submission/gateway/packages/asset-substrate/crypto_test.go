package substrate

import (
	"bytes"
	"testing"
)

func TestEncryptDecrypt(t *testing.T) {
	key := DeriveKey("test-passphrase-32byte!!")
	plaintext := []byte("Hello, Asset Substrate!")

	payload, err := Encrypt(plaintext, key, "key-001")
	if err != nil {
		t.Fatalf("Encrypt failed: %v", err)
	}

	if payload.Algorithm != "AES-256-GCM" {
		t.Errorf("expected AES-256-GCM, got %s", payload.Algorithm)
	}
	if payload.KeyID != "key-001" {
		t.Errorf("expected key-001, got %s", payload.KeyID)
	}
	if payload.Ciphertext == "" {
		t.Fatal("ciphertext is empty")
	}

	decrypted, err := Decrypt(payload, key)
	if err != nil {
		t.Fatalf("Decrypt failed: %v", err)
	}

	if !bytes.Equal(plaintext, decrypted) {
		t.Errorf("decrypted text mismatch: got %s, want %s", string(decrypted), string(plaintext))
	}
}

func TestEncryptWrongKeySize(t *testing.T) {
	_, err := Encrypt([]byte("data"), []byte("short-key"), "")
	if err != ErrInvalidKey {
		t.Errorf("expected ErrInvalidKey, got %v", err)
	}
}

func TestDecryptWrongKey(t *testing.T) {
	key := DeriveKey("correct-passphrase")
	plaintext := []byte("secret data")

	payload, err := Encrypt(plaintext, key, "")
	if err != nil {
		t.Fatalf("Encrypt failed: %v", err)
	}

	wrongKey := DeriveKey("wrong-passphrase")
	_, err = Decrypt(payload, wrongKey)
	if err != ErrDecryptFailed {
		t.Errorf("expected ErrDecryptFailed, got %v", err)
	}
}

func TestDecryptCorruptedCiphertext(t *testing.T) {
	key := DeriveKey("test-key")

	payload := &EncryptedPayload{
		Ciphertext: "AAAA-invalid-base64!!!",
		Algorithm:  "AES-256-GCM",
	}

	_, err := Decrypt(payload, key)
	if err == nil {
		t.Fatal("expected error for corrupted ciphertext")
	}
}

func TestDecryptTooShortCiphertext(t *testing.T) {
	key := DeriveKey("test-key")

	payload := &EncryptedPayload{
		Ciphertext: "dG9vLXNo", // base64 of "too-sh"
		Algorithm:  "AES-256-GCM",
	}

	_, err := Decrypt(payload, key)
	if err != ErrCiphertextTooShort {
		t.Errorf("expected ErrCiphertextTooShort, got %v", err)
	}
}

func TestDeriveKeyConsistency(t *testing.T) {
	k1 := DeriveKey("same-passphrase")
	k2 := DeriveKey("same-passphrase")
	if !bytes.Equal(k1, k2) {
		t.Error("DeriveKey should be deterministic")
	}
	if len(k1) != AESKeySize {
		t.Errorf("expected key size %d, got %d", AESKeySize, len(k1))
	}

	k3 := DeriveKey("different-passphrase")
	if bytes.Equal(k1, k3) {
		t.Error("DeriveKey should produce different keys for different passphrases")
	}
}

func TestEncryptUniqueNonce(t *testing.T) {
	key := DeriveKey("test-key")
	plaintext := []byte("same data")

	p1, _ := Encrypt(plaintext, key, "")
	p2, _ := Encrypt(plaintext, key, "")

	if p1.Ciphertext == p2.Ciphertext {
		t.Error("two encryptions of same plaintext should produce different ciphertext (random nonce)")
	}
}

func TestHashHex(t *testing.T) {
	data := []byte("hello")
	h := HashHex(data)
	if len(h) != 64 {
		t.Errorf("SHA-256 hex should be 64 chars, got %d", len(h))
	}
	// Known SHA-256 of "hello"
	expected := "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
	if h != expected {
		t.Errorf("hash mismatch: got %s, want %s", h, expected)
	}
}
