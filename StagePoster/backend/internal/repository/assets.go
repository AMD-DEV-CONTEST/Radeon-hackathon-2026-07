package repository

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func (r *Repository) MigrateAssets(
	ctx context.Context,
) error {
	statements := []string{
		`
		CREATE TABLE IF NOT EXISTS assets (
			id TEXT PRIMARY KEY,
			kind TEXT NOT NULL,

			original_name TEXT NOT NULL,
			filename TEXT NOT NULL,
			mime_type TEXT NOT NULL,

			size_bytes INTEGER NOT NULL,
			sha256 TEXT NOT NULL,
			storage_path TEXT NOT NULL,

			width INTEGER NOT NULL DEFAULT 0,
			height INTEGER NOT NULL DEFAULT 0,

			-- Processing state
			process_status TEXT NOT NULL DEFAULT 'pending',
			process_error TEXT,
			processed_at TEXT,
			mask_path TEXT,
			analysis_json TEXT,
			dominant_colors TEXT,
			process_version TEXT,

			created_at TEXT NOT NULL
		)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_assets_created_at
		ON assets(created_at DESC)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_assets_kind
		ON assets(kind, created_at DESC)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_assets_sha256
		ON assets(sha256)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_assets_process_status
		ON assets(process_status, created_at DESC)
		`,
	}

	for _, statement := range statements {
		if _, err := r.db.ExecContext(ctx, statement); err != nil {
			return fmt.Errorf(
				"run assets migration: %w",
				err,
			)
		}
	}

	// Migrate existing table if it lacks the new columns (idempotent).
	alterStatements := []string{
		"ALTER TABLE assets ADD COLUMN process_status TEXT NOT NULL DEFAULT 'pending'",
		"ALTER TABLE assets ADD COLUMN process_error TEXT",
		"ALTER TABLE assets ADD COLUMN processed_at TEXT",
		"ALTER TABLE assets ADD COLUMN mask_path TEXT",
		"ALTER TABLE assets ADD COLUMN analysis_json TEXT",
		"ALTER TABLE assets ADD COLUMN dominant_colors TEXT",
		"ALTER TABLE assets ADD COLUMN process_version TEXT",
		"ALTER TABLE assets ADD COLUMN cutout_status TEXT NOT NULL DEFAULT 'unsupported'",
		"ALTER TABLE assets ADD COLUMN has_alpha INTEGER NOT NULL DEFAULT 0",
	}

	for _, stmt := range alterStatements {
		if _, err := r.db.ExecContext(ctx, stmt); err != nil {
			if !strings.Contains(err.Error(), "duplicate column") &&
				!strings.Contains(err.Error(), "already exists") {
				return fmt.Errorf(
					"alter assets table: %w",
					err,
				)
			}
		}
	}

	// mask_path 里存的从来不是蒙版，而是源文件的逐字节副本（连扩展名都硬编码成
	// .png，JPEG 上传会得到一个装着 JPEG 字节的 .png）。没有任何代码消费它，
	// 合成器根本看不到蒙版。留着这个值等于对外宣称抠图做过了。清掉。
	// 磁盘上的旧 mask_*.png 文件不动，避免误删用户数据。
	if _, err := r.db.ExecContext(
		ctx,
		`
		UPDATE assets
		SET mask_path = ''
		WHERE mask_path IS NOT NULL AND mask_path != ''
		`,
	); err != nil {
		return fmt.Errorf(
			"clear placeholder mask paths: %w",
			err,
		)
	}

	return nil
}

func (r *Repository) CreateAsset(
	ctx context.Context,
	asset domain.Asset,
) error {
	_, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO assets (
			id,
			kind,
			original_name,
			filename,
			mime_type,
			size_bytes,
			sha256,
			storage_path,
			width,
			height,
			process_status,
			process_error,
			processed_at,
			mask_path,
			analysis_json,
			dominant_colors,
			process_version,
			created_at
		)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`,
		asset.ID,
		asset.Kind,
		asset.OriginalName,
		asset.Filename,
		asset.MimeType,
		asset.SizeBytes,
		asset.SHA256,
		asset.StoragePath,
		asset.Width,
		asset.Height,
		asset.ProcessStatus,
		nullableString(asset.ProcessError),
		formatOptionalTime(asset.ProcessedAt),
		nullableString(asset.MaskPath),
		nullableString(asset.AnalysisJSON),
		strings.Join(asset.DominantColors, ","),
		nullableString(asset.ProcessVersion),
		formatTime(asset.CreatedAt),
	)
	if err != nil {
		return fmt.Errorf("insert asset: %w", err)
	}

	return nil
}

func (r *Repository) GetAsset(
	ctx context.Context,
	assetID string,
) (domain.Asset, error) {
	row := r.db.QueryRowContext(
		ctx,
		`
		SELECT
			id,
			kind,
			original_name,
			filename,
			mime_type,
			size_bytes,
			sha256,
			storage_path,
			width,
			height,
			process_status,
			process_error,
			processed_at,
			mask_path,
			analysis_json,
			dominant_colors,
			process_version,
			cutout_status,
			has_alpha,
			created_at
		FROM assets
		WHERE id = ?
		`,
		assetID,
	)

	asset, err := scanAsset(row)

	if errors.Is(err, sql.ErrNoRows) {
		return domain.Asset{}, ErrNotFound
	}

	if err != nil {
		return domain.Asset{}, fmt.Errorf(
			"get asset: %w",
			err,
		)
	}

	return asset, nil
}

// CountAssets 返回 assets 表总行数。
func (r *Repository) CountAssets(
	ctx context.Context,
) (int, error) {
	var total int

	if err := r.db.QueryRowContext(
		ctx,
		`SELECT COUNT(*) FROM assets`,
	).Scan(&total); err != nil {
		return 0, fmt.Errorf("count assets: %w", err)
	}

	return total, nil
}

func (r *Repository) ListAssets(
	ctx context.Context,
	page domain.Page,
) ([]domain.Asset, error) {

	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			id,
			kind,
			original_name,
			filename,
			mime_type,
			size_bytes,
			sha256,
			storage_path,
			width,
			height,
			process_status,
			process_error,
			processed_at,
			mask_path,
			analysis_json,
			dominant_colors,
			process_version,
			cutout_status,
			has_alpha,
			created_at
		FROM assets
		ORDER BY created_at DESC
		LIMIT ? OFFSET ?
		`,
		page.Limit,
		page.Offset,
	)
	if err != nil {
		return nil, fmt.Errorf(
			"list assets: %w",
			err,
		)
	}
	defer rows.Close()

	assets := make([]domain.Asset, 0, page.Limit)

	for rows.Next() {
		asset, err := scanAsset(rows)
		if err != nil {
			return nil, fmt.Errorf(
				"scan asset: %w",
				err,
			)
		}

		assets = append(assets, asset)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf(
			"iterate assets: %w",
			err,
		)
	}

	return assets, nil
}

func (r *Repository) UpdateAssetProcessStatus(
	ctx context.Context,
	assetID string,
	status domain.AssetProcessStatus,
	processError string,
	processedAt *time.Time,
	maskPath string,
	analysisJSON string,
	cutout domain.AssetCutout,
) error {
	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE assets
		SET
			process_status = ?,
			process_error = ?,
			processed_at = ?,
			mask_path = ?,
			analysis_json = ?,
			process_version = ?,
			cutout_status = ?,
			has_alpha = ?
		WHERE id = ?
		`,
		status,
		nullableString(processError),
		formatOptionalTime(processedAt),
		nullableString(maskPath),
		nullableString(analysisJSON),
		domain.AssetProcessVersion,
		string(cutout.Status),
		cutout.HasAlpha,
		assetID,
	)
	if err != nil {
		return fmt.Errorf("update asset process status: %w", err)
	}

	return requireAffected(result)
}

func scanAsset(source scanner) (domain.Asset, error) {
	var asset domain.Asset
	var createdAt string
	var processError sql.NullString
	var processedAt sql.NullString
	var maskPath sql.NullString
	var analysisJSON sql.NullString
	var dominantColors sql.NullString
	var processVersion sql.NullString
	var cutoutStatus sql.NullString

	err := source.Scan(
		&asset.ID,
		&asset.Kind,
		&asset.OriginalName,
		&asset.Filename,
		&asset.MimeType,
		&asset.SizeBytes,
		&asset.SHA256,
		&asset.StoragePath,
		&asset.Width,
		&asset.Height,
		&asset.ProcessStatus,
		&processError,
		&processedAt,
		&maskPath,
		&analysisJSON,
		&dominantColors,
		&processVersion,
		&cutoutStatus,
		&asset.Cutout.HasAlpha,
		&createdAt,
	)
	if err != nil {
		return domain.Asset{}, err
	}

	asset.ProcessError = processError.String
	asset.MaskPath = maskPath.String
	asset.AnalysisJSON = analysisJSON.String
	asset.ProcessVersion = processVersion.String

	asset.Cutout.Status = domain.NormalizeAssetCutoutStatus(
		domain.AssetCutoutStatus(cutoutStatus.String),
	)

	if processedAt.Valid && processedAt.String != "" {
		parsed, parseErr := parseTime(processedAt.String)
		if parseErr == nil {
			asset.ProcessedAt = &parsed
		}
	}

	if dominantColors.Valid && dominantColors.String != "" {
		asset.DominantColors = strings.Split(dominantColors.String, ",")
	}

	asset.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.Asset{}, err
	}

	return asset, nil
}
