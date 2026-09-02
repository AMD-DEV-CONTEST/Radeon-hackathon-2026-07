package storage

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	_ "image/jpeg"
	_ "image/png"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

var (
	ErrEmptyAsset           = errors.New("uploaded asset is empty")
	ErrAssetTooLarge        = errors.New("uploaded asset is too large")
	ErrUnsupportedAssetType = errors.New("unsupported asset type")
)

type AssetStore struct {
	root     string
	maxBytes int64
}

func NewAssetStore(
	root string,
	maxBytes int64,
) (*AssetStore, error) {
	root = strings.TrimSpace(root)

	if root == "" {
		return nil, errors.New("asset storage root is required")
	}

	if maxBytes <= 0 {
		maxBytes = 20 << 20
	}

	if err := os.MkdirAll(root, 0o755); err != nil {
		return nil, fmt.Errorf(
			"create asset storage root: %w",
			err,
		)
	}

	return &AssetStore{
		root:     root,
		maxBytes: maxBytes,
	}, nil
}

func (s *AssetStore) Save(
	kind domain.AssetKind,
	originalName string,
	body io.Reader,
) (domain.Asset, error) {
	buffered := bufio.NewReader(body)

	header, peekErr := buffered.Peek(512)
	if len(header) == 0 {
		return domain.Asset{}, ErrEmptyAsset
	}

	if peekErr != nil &&
		!errors.Is(peekErr, io.EOF) &&
		!errors.Is(peekErr, bufio.ErrBufferFull) {
		return domain.Asset{}, fmt.Errorf(
			"inspect uploaded asset: %w",
			peekErr,
		)
	}

	mimeType := http.DetectContentType(header)

	extension, err := assetExtension(mimeType)
	if err != nil {
		return domain.Asset{}, err
	}

	assetID, err := domain.NewID("asset_")
	if err != nil {
		return domain.Asset{}, err
	}

	now := time.Now().UTC()

	directory := filepath.Join(
		s.root,
		now.Format("2006"),
		now.Format("01"),
	)

	if err := os.MkdirAll(directory, 0o755); err != nil {
		return domain.Asset{}, fmt.Errorf(
			"create asset directory: %w",
			err,
		)
	}

	filename := assetID + extension
	finalPath := filepath.Join(directory, filename)

	tempFile, err := os.CreateTemp(directory, ".asset-*")
	if err != nil {
		return domain.Asset{}, fmt.Errorf(
			"create asset temporary file: %w",
			err,
		)
	}

	tempPath := tempFile.Name()

	cleanup := func() {
		_ = tempFile.Close()
		_ = os.Remove(tempPath)
	}

	hasher := sha256.New()

	limited := &io.LimitedReader{
		R: buffered,
		N: s.maxBytes + 1,
	}

	written, err := io.Copy(
		io.MultiWriter(tempFile, hasher),
		limited,
	)
	if err != nil {
		cleanup()
		return domain.Asset{}, fmt.Errorf(
			"write uploaded asset: %w",
			err,
		)
	}

	if written == 0 {
		cleanup()
		return domain.Asset{}, ErrEmptyAsset
	}

	if written > s.maxBytes {
		cleanup()
		return domain.Asset{}, ErrAssetTooLarge
	}

	if err := tempFile.Sync(); err != nil {
		cleanup()
		return domain.Asset{}, fmt.Errorf(
			"sync uploaded asset: %w",
			err,
		)
	}

	if err := tempFile.Close(); err != nil {
		_ = os.Remove(tempPath)
		return domain.Asset{}, fmt.Errorf(
			"close uploaded asset: %w",
			err,
		)
	}

	if err := os.Rename(tempPath, finalPath); err != nil {
		_ = os.Remove(tempPath)
		return domain.Asset{}, fmt.Errorf(
			"commit uploaded asset: %w",
			err,
		)
	}

	width, height := imageDimensions(finalPath)

	return domain.Asset{
		ID:           assetID,
		Kind:         kind,
		OriginalName: filepath.Base(originalName),
		Filename:     filename,
		MimeType:     mimeType,
		SizeBytes:    written,
		SHA256:       hex.EncodeToString(hasher.Sum(nil)),
		StoragePath:  finalPath,
		Width:        width,
		Height:       height,
		CreatedAt:    now,
	}, nil
}

func (s *AssetStore) Open(
	asset domain.Asset,
) (*os.File, error) {
	rootPath, err := filepath.Abs(s.root)
	if err != nil {
		return nil, err
	}

	assetPath, err := filepath.Abs(asset.StoragePath)
	if err != nil {
		return nil, err
	}

	relativePath, err := filepath.Rel(rootPath, assetPath)
	if err != nil {
		return nil, err
	}

	if relativePath == ".." ||
		strings.HasPrefix(
			relativePath,
			".."+string(filepath.Separator),
		) {
		return nil, errors.New(
			"asset path is outside storage root",
		)
	}

	file, err := os.Open(assetPath)
	if err != nil {
		return nil, fmt.Errorf(
			"open stored asset: %w",
			err,
		)
	}

	return file, nil
}

func (s *AssetStore) Delete(
	asset domain.Asset,
) error {
	if asset.StoragePath == "" {
		return nil
	}

	if err := os.Remove(asset.StoragePath); err != nil &&
		!errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf(
			"delete stored asset: %w",
			err,
		)
	}

	return nil
}

func assetExtension(
	mimeType string,
) (string, error) {
	switch mimeType {
	case "image/png":
		return ".png", nil

	case "image/jpeg":
		return ".jpg", nil

	default:
		return "", fmt.Errorf(
			"%w: %s",
			ErrUnsupportedAssetType,
			mimeType,
		)
	}
}
