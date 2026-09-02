package repository

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func (r *Repository) MigratePosterOutputs(
	ctx context.Context,
) error {
	_, err := r.db.ExecContext(
		ctx,
		`
		CREATE TABLE IF NOT EXISTS poster_outputs (
			id TEXT PRIMARY KEY,
			poster_id TEXT NOT NULL,
			candidate_id TEXT NOT NULL,

			kind TEXT NOT NULL,
			filename TEXT NOT NULL,
			mime_type TEXT NOT NULL,
			storage_path TEXT NOT NULL,

			width INTEGER NOT NULL,
			height INTEGER NOT NULL,

			created_at TEXT NOT NULL,

			FOREIGN KEY(poster_id)
				REFERENCES poster_requests(id)
				ON DELETE CASCADE,

			FOREIGN KEY(candidate_id)
				REFERENCES poster_candidates(id),

			UNIQUE(poster_id, kind)
		)
		`,
	)
	if err != nil {
		return fmt.Errorf(
			"create poster outputs table: %w",
			err,
		)
	}

	return nil
}

func (r *Repository) GetSelectedCandidate(
	ctx context.Context,
	posterID string,
) (domain.CandidateRecord, error) {
	row := r.db.QueryRowContext(
		ctx,
		`
		SELECT
			id,
			poster_id,
			job_id,
			variant_index,
			variant_key,
			variant_name,
			spec_json,
			compiled_prompt,
			seed,
			attempt,
			status,
			passed,
			selected,
			error_message,
			created_at,
			updated_at
		FROM poster_candidates
		WHERE poster_id = ? AND selected = 1
		LIMIT 1
		`,
		posterID,
	)

	var candidate domain.CandidateRecord
	var errorMessage sql.NullString
	var createdAt string
	var updatedAt string

	err := row.Scan(
		&candidate.ID,
		&candidate.PosterID,
		&candidate.JobID,
		&candidate.VariantIndex,
		&candidate.VariantKey,
		&candidate.VariantName,
		&candidate.SpecJSON,
		&candidate.CompiledPrompt,
		&candidate.Seed,
		&candidate.Attempt,
		&candidate.Status,
		&candidate.Passed,
		&candidate.Selected,
		&errorMessage,
		&createdAt,
		&updatedAt,
	)

	if errors.Is(err, sql.ErrNoRows) {
		return domain.CandidateRecord{}, ErrNotFound
	}

	if err != nil {
		return domain.CandidateRecord{},
			fmt.Errorf(
				"get selected candidate: %w",
				err,
			)
	}

	candidate.ErrorMessage = errorMessage.String

	candidate.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.CandidateRecord{}, err
	}

	candidate.UpdatedAt, err = parseTime(updatedAt)
	if err != nil {
		return domain.CandidateRecord{}, err
	}

	return candidate, nil
}

func (r *Repository) GetCompositionAsset(
	ctx context.Context,
	assetID string,
) (domain.CompositionAsset, error) {
	row := r.db.QueryRowContext(
		ctx,
		`
		SELECT
			id,
			mime_type,
			storage_path,
			width,
			height
		FROM assets
		WHERE id = ?
		`,
		assetID,
	)

	var asset domain.CompositionAsset

	err := row.Scan(
		&asset.ID,
		&asset.MimeType,
		&asset.StoragePath,
		&asset.Width,
		&asset.Height,
	)

	if errors.Is(err, sql.ErrNoRows) {
		return domain.CompositionAsset{}, ErrNotFound
	}

	if err != nil {
		return domain.CompositionAsset{},
			fmt.Errorf(
				"get composition asset: %w",
				err,
			)
	}

	return asset, nil
}

func (r *Repository) UpsertPosterOutput(
	ctx context.Context,
	output domain.PosterOutput,
) error {
	_, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO poster_outputs (
			id,
			poster_id,
			candidate_id,
			kind,
			filename,
			mime_type,
			storage_path,
			width,
			height,
			created_at
		)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(poster_id, kind)
		DO UPDATE SET
			candidate_id = excluded.candidate_id,
			filename = excluded.filename,
			mime_type = excluded.mime_type,
			storage_path = excluded.storage_path,
			width = excluded.width,
			height = excluded.height,
			created_at = excluded.created_at
		`,
		output.ID,
		output.PosterID,
		output.CandidateID,
		output.Kind,
		output.Filename,
		output.MimeType,
		output.StoragePath,
		output.Width,
		output.Height,
		formatTime(output.CreatedAt),
	)
	if err != nil {
		return fmt.Errorf(
			"upsert poster output: %w",
			err,
		)
	}

	return nil
}

func (r *Repository) GetPosterOutput(
	ctx context.Context,
	posterID string,
	kind string,
) (domain.PosterOutput, error) {
	row := r.db.QueryRowContext(
		ctx,
		`
		SELECT
			id,
			poster_id,
			candidate_id,
			kind,
			filename,
			mime_type,
			storage_path,
			width,
			height,
			created_at
		FROM poster_outputs
		WHERE poster_id = ? AND kind = ?
		`,
		posterID,
		kind,
	)

	var output domain.PosterOutput
	var createdAt string

	err := row.Scan(
		&output.ID,
		&output.PosterID,
		&output.CandidateID,
		&output.Kind,
		&output.Filename,
		&output.MimeType,
		&output.StoragePath,
		&output.Width,
		&output.Height,
		&createdAt,
	)

	if errors.Is(err, sql.ErrNoRows) {
		return domain.PosterOutput{}, ErrNotFound
	}

	if err != nil {
		return domain.PosterOutput{},
			fmt.Errorf(
				"get poster output: %w",
				err,
			)
	}

	output.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.PosterOutput{}, err
	}

	return output, nil
}

func (r *Repository) CompletePoster(
	ctx context.Context,
	posterID string,
) error {
	now := time.Now().UTC()

	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE poster_requests
		SET
			status = ?,
			error_message = NULL,
			completed_at = ?,
			updated_at = ?
		WHERE id = ?
		`,
		domain.PosterStatusSucceeded,
		formatTime(now),
		formatTime(now),
		posterID,
	)
	if err != nil {
		return err
	}

	return requireAffected(result)
}
