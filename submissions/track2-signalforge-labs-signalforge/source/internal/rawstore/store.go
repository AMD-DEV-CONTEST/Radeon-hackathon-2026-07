package rawstore

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type Input struct {
	SourceURI   string
	MediaType   string
	Content     []byte
	ContentSHA  string
	RetrievedAt time.Time
}

type Record struct {
	SchemaVersion string    `json:"schema_version"`
	RecordID      string    `json:"record_id"`
	SourceURI     string    `json:"source_uri"`
	MediaType     string    `json:"media_type"`
	ContentSHA    string    `json:"content_sha256"`
	ContentBytes  int       `json:"content_bytes"`
	RetrievedAt   time.Time `json:"retrieved_at"`
	PayloadPath   string    `json:"payload_path"`
	RecordPath    string    `json:"record_path"`
}

type Store struct {
	root string
}

func New(root string) (Store, error) {
	if strings.TrimSpace(root) == "" {
		return Store{}, errors.New("raw store root is required")
	}
	absolute, err := filepath.Abs(root)
	if err != nil {
		return Store{}, err
	}
	return Store{root: absolute}, nil
}

func (store Store) Put(input Input) (Record, error) {
	if input.RetrievedAt.IsZero() || len(input.Content) == 0 || input.MediaType == "" {
		return Record{}, errors.New("retrieved_at, non-empty content, and media_type are required")
	}
	sourceURI, err := sanitizeSourceURI(input.SourceURI)
	if err != nil {
		return Record{}, err
	}
	digest := sha256.Sum256(input.Content)
	contentSHA := hex.EncodeToString(digest[:])
	if input.ContentSHA != "" && !strings.EqualFold(input.ContentSHA, contentSHA) {
		return Record{}, errors.New("declared content hash does not match payload")
	}
	blobDirectory := filepath.Join(store.root, "blobs", "sha256", contentSHA[:2], contentSHA)
	if err := os.MkdirAll(blobDirectory, 0o750); err != nil {
		return Record{}, err
	}
	payloadPath := filepath.Join(blobDirectory, "payload")
	if err := writeImmutable(payloadPath, input.Content, 0o640); err != nil {
		return Record{}, err
	}
	retrievedAt := input.RetrievedAt.UTC()
	recordDigest := sha256.Sum256([]byte(sourceURI + "\n" + contentSHA + "\n" + retrievedAt.Format(time.RFC3339Nano)))
	recordID := hex.EncodeToString(recordDigest[:])
	recordRelativePath := filepath.Join("records", "sha256", recordID[:2], recordID+".json")
	record := Record{
		SchemaVersion: "signalforge/raw-record/v1", RecordID: recordID, SourceURI: sourceURI,
		MediaType: input.MediaType, ContentSHA: contentSHA, ContentBytes: len(input.Content),
		RetrievedAt: retrievedAt,
		PayloadPath: filepath.ToSlash(filepath.Join("blobs", "sha256", contentSHA[:2], contentSHA, "payload")),
		RecordPath:  filepath.ToSlash(recordRelativePath),
	}
	metadata, err := json.MarshalIndent(record, "", "  ")
	if err != nil {
		return Record{}, err
	}
	metadata = append(metadata, '\n')
	recordPath := filepath.Join(store.root, recordRelativePath)
	if err := os.MkdirAll(filepath.Dir(recordPath), 0o750); err != nil {
		return Record{}, err
	}
	if err := writeImmutable(recordPath, metadata, 0o640); err != nil {
		return Record{}, err
	}
	return record, nil
}

func (store Store) ReadPayload(record Record) ([]byte, error) {
	if record.ContentSHA == "" || record.PayloadPath == "" {
		return nil, errors.New("record content hash and payload path are required")
	}
	path := filepath.Join(store.root, filepath.FromSlash(record.PayloadPath))
	relative, err := filepath.Rel(store.root, path)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(os.PathSeparator)) {
		return nil, errors.New("payload path escapes raw store")
	}
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	digest := sha256.Sum256(content)
	if hex.EncodeToString(digest[:]) != record.ContentSHA {
		return nil, errors.New("stored payload hash does not match raw record")
	}
	return content, nil
}

func writeImmutable(path string, content []byte, mode os.FileMode) error {
	existing, err := os.ReadFile(path)
	if err == nil {
		if !bytes.Equal(existing, content) {
			return fmt.Errorf("immutable record conflict at %s", path)
		}
		return nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	temporary, err := os.CreateTemp(filepath.Dir(path), ".signalforge-write-*")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if err := temporary.Chmod(mode); err != nil {
		temporary.Close()
		return err
	}
	if _, err := temporary.Write(content); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	return os.Rename(temporaryPath, path)
}

func sanitizeSourceURI(raw string) (string, error) {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return "", errors.New("valid source URI is required")
	}
	parsed.User = nil
	query := parsed.Query()
	for name := range query {
		lower := strings.ToLower(name)
		if strings.Contains(lower, "key") || strings.Contains(lower, "token") || strings.Contains(lower, "secret") || strings.Contains(lower, "auth") {
			query.Set(name, "REDACTED")
		}
	}
	parsed.RawQuery = query.Encode()
	parsed.Fragment = ""
	return parsed.String(), nil
}
