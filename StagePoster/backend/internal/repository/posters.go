package repository

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func (r *Repository) MigratePosters(
	ctx context.Context,
) error {
	statements := []string{
		`
		CREATE TABLE IF NOT EXISTS poster_requests (
			id TEXT PRIMARY KEY,
			status TEXT NOT NULL,
			style_key TEXT NOT NULL,

			event_json TEXT NOT NULL,
			branding_json TEXT NOT NULL,
			visual_json TEXT NOT NULL,
			goal_json TEXT NOT NULL,

			selected_candidate_id TEXT,
			error_message TEXT,

			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			completed_at TEXT
		)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_poster_requests_created
		ON poster_requests(created_at DESC)
		`,
		`
		CREATE TABLE IF NOT EXISTS poster_candidates (
			id TEXT PRIMARY KEY,
			poster_id TEXT NOT NULL,
			job_id TEXT NOT NULL,

			variant_index INTEGER NOT NULL,
			variant_key TEXT NOT NULL,
			variant_name TEXT NOT NULL,

			spec_json TEXT NOT NULL,
			compiled_prompt TEXT NOT NULL,

			seed INTEGER NOT NULL,
			attempt INTEGER NOT NULL,
			status TEXT NOT NULL,

			passed INTEGER NOT NULL DEFAULT 0,
			selected INTEGER NOT NULL DEFAULT 0,
			error_message TEXT,

			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,

			FOREIGN KEY(poster_id)
				REFERENCES poster_requests(id)
				ON DELETE CASCADE,

			FOREIGN KEY(job_id)
				REFERENCES jobs(id),

			UNIQUE(poster_id, variant_index)
		)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_candidates_poster
		ON poster_candidates(poster_id, variant_index)
		`,
	}

	for _, statement := range statements {
		if _, err := r.db.ExecContext(ctx, statement); err != nil {
			return fmt.Errorf(
				"run poster migration: %w",
				err,
			)
		}
	}

	return nil
}

func (r *Repository) CreatePoster(
	ctx context.Context,
	poster domain.PosterRecord,
) error {
	_, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO poster_requests (
			id,
			status,
			style_key,
			event_json,
			branding_json,
			visual_json,
			goal_json,
			selected_candidate_id,
			error_message,
			created_at,
			updated_at,
			completed_at
		)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`,
		poster.ID,
		poster.Status,
		poster.StyleKey,
		poster.EventJSON,
		poster.BrandingJSON,
		poster.VisualJSON,
		poster.GoalJSON,
		nullableString(poster.SelectedCandidateID),
		nullableString(poster.ErrorMessage),
		formatTime(poster.CreatedAt),
		formatTime(poster.UpdatedAt),
		formatOptionalTime(poster.CompletedAt),
	)
	if err != nil {
		return fmt.Errorf("insert poster request: %w", err)
	}

	return nil
}

func (r *Repository) CreateCandidate(
	ctx context.Context,
	candidate domain.CandidateRecord,
) error {
	_, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO poster_candidates (
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
		)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`,
		candidate.ID,
		candidate.PosterID,
		candidate.JobID,
		candidate.VariantIndex,
		candidate.VariantKey,
		candidate.VariantName,
		candidate.SpecJSON,
		candidate.CompiledPrompt,
		candidate.Seed,
		candidate.Attempt,
		candidate.Status,
		candidate.Passed,
		candidate.Selected,
		nullableString(candidate.ErrorMessage),
		formatTime(candidate.CreatedAt),
		formatTime(candidate.UpdatedAt),
	)
	if err != nil {
		return fmt.Errorf("insert poster candidate: %w", err)
	}

	return nil
}

func (r *Repository) GetPoster(
	ctx context.Context,
	posterID string,
) (domain.PosterRecord, error) {
	row := r.db.QueryRowContext(
		ctx,
		`
		SELECT
			id,
			status,
			style_key,
			event_json,
			branding_json,
			visual_json,
			goal_json,
			selected_candidate_id,
			error_message,
			created_at,
			updated_at,
			completed_at
		FROM poster_requests
		WHERE id = ?
		`,
		posterID,
	)

	var poster domain.PosterRecord
	var selectedID sql.NullString
	var errorMessage sql.NullString
	var completedAt sql.NullString
	var createdAt string
	var updatedAt string

	err := row.Scan(
		&poster.ID,
		&poster.Status,
		&poster.StyleKey,
		&poster.EventJSON,
		&poster.BrandingJSON,
		&poster.VisualJSON,
		&poster.GoalJSON,
		&selectedID,
		&errorMessage,
		&createdAt,
		&updatedAt,
		&completedAt,
	)

	if errors.Is(err, sql.ErrNoRows) {
		return domain.PosterRecord{}, ErrNotFound
	}

	if err != nil {
		return domain.PosterRecord{}, fmt.Errorf(
			"get poster request: %w",
			err,
		)
	}

	poster.SelectedCandidateID = selectedID.String
	poster.ErrorMessage = errorMessage.String

	poster.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.PosterRecord{}, err
	}

	poster.UpdatedAt, err = parseTime(updatedAt)
	if err != nil {
		return domain.PosterRecord{}, err
	}

	poster.CompletedAt, err = parseOptionalTime(completedAt)
	if err != nil {
		return domain.PosterRecord{}, err
	}

	return poster, nil
}

func (r *Repository) ListCandidates(
	ctx context.Context,
	posterID string,
) ([]domain.CandidateRecord, error) {
	rows, err := r.db.QueryContext(
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
		WHERE poster_id = ?
		ORDER BY variant_index ASC
		`,
		posterID,
	)
	if err != nil {
		return nil, fmt.Errorf(
			"list poster candidates: %w",
			err,
		)
	}
	defer rows.Close()

	var candidates []domain.CandidateRecord

	for rows.Next() {
		var candidate domain.CandidateRecord
		var errorMessage sql.NullString
		var createdAt string
		var updatedAt string

		if err := rows.Scan(
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
		); err != nil {
			return nil, err
		}

		candidate.ErrorMessage = errorMessage.String

		candidate.CreatedAt, err = parseTime(createdAt)
		if err != nil {
			return nil, err
		}

		candidate.UpdatedAt, err = parseTime(updatedAt)
		if err != nil {
			return nil, err
		}

		candidates = append(candidates, candidate)
	}

	return candidates, rows.Err()
}

func (r *Repository) GetCandidate(
	ctx context.Context,
	posterID string,
	candidateID string,
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
		WHERE poster_id = ? AND id = ?
		`,
		posterID,
		candidateID,
	)

	var candidate domain.CandidateRecord
	var errorMessage sql.NullString
	var createdAt string
	var updatedAt string

	if err := row.Scan(
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
	); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return domain.CandidateRecord{}, ErrNotFound
		}
		return domain.CandidateRecord{}, fmt.Errorf(
			"get candidate: %w",
			err,
		)
	}

	candidate.ErrorMessage = errorMessage.String

	var err error
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

func (r *Repository) UpdatePosterStatus(
	ctx context.Context,
	posterID string,
	status domain.PosterStatus,
	errorMessage string,
) error {
	now := time.Now().UTC()

	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE poster_requests
		SET status = ?, error_message = ?, updated_at = ?
		WHERE id = ?
		`,
		status,
		nullableString(errorMessage),
		formatTime(now),
		posterID,
	)
	if err != nil {
		return err
	}

	return requireAffected(result)
}

func (r *Repository) UpdateCandidateState(
	ctx context.Context,
	candidateID string,
	status domain.CandidateStatus,
	passed bool,
	errorMessage string,
) error {
	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE poster_candidates
		SET
			status = ?,
			passed = ?,
			error_message = ?,
			updated_at = ?
		WHERE id = ?
		`,
		status,
		passed,
		nullableString(errorMessage),
		formatTime(time.Now().UTC()),
		candidateID,
	)
	if err != nil {
		return err
	}

	return requireAffected(result)
}

func (r *Repository) ReplaceCandidateJob(
	ctx context.Context,
	candidateID string,
	jobID string,
	seed int64,
	attempt int,
) error {
	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE poster_candidates
		SET
			job_id = ?,
			seed = ?,
			attempt = ?,
			status = ?,
			passed = 0,
			error_message = NULL,
			updated_at = ?
		WHERE id = ?
		`,
		jobID,
		seed,
		attempt,
		domain.CandidateStatusRetrying,
		formatTime(time.Now().UTC()),
		candidateID,
	)
	if err != nil {
		return err
	}

	return requireAffected(result)
}

func (r *Repository) SelectCandidate(
	ctx context.Context,
	posterID string,
	candidateID string,
) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()

	var passed bool

	err = tx.QueryRowContext(
		ctx,
		`
		SELECT passed
		FROM poster_candidates
		WHERE id = ? AND poster_id = ?
		`,
		candidateID,
		posterID,
	).Scan(&passed)

	if errors.Is(err, sql.ErrNoRows) {
		return ErrNotFound
	}

	if err != nil {
		return err
	}

	if !passed {
		return errors.New("candidate is not ready")
	}

	now := formatTime(time.Now().UTC())

	if _, err := tx.ExecContext(
		ctx,
		`
		UPDATE poster_candidates
		SET selected = CASE WHEN id = ? THEN 1 ELSE 0 END,
		    updated_at = ?
		WHERE poster_id = ?
		`,
		candidateID,
		now,
		posterID,
	); err != nil {
		return err
	}

	if _, err := tx.ExecContext(
		ctx,
		`
		UPDATE poster_requests
		SET
			status = ?,
			selected_candidate_id = ?,
			updated_at = ?
		WHERE id = ?
		`,
		domain.PosterStatusSelected,
		candidateID,
		now,
		posterID,
	); err != nil {
		return err
	}

	return tx.Commit()
}

func (r *Repository) ListActivePosters(
	ctx context.Context,
	limit int,
) ([]domain.PosterRecord, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}

	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			id,
			status,
			style_key,
			event_json,
			branding_json,
			visual_json,
			goal_json,
			selected_candidate_id,
			error_message,
			created_at,
			updated_at,
			completed_at
		FROM poster_requests
		WHERE status IN (?, ?, ?, ?, ?, ?)
		ORDER BY created_at ASC
		LIMIT ?
		`,
		domain.PosterStatusPlanning,
		domain.PosterStatusGenerating,
		domain.PosterStatusValidating,
		domain.PosterStatusPartialReady,
		domain.PosterStatusSelected,
		domain.PosterStatusComposing,
		limit,
	)
	if err != nil {
		return nil, fmt.Errorf(
			"list active poster requests: %w",
			err,
		)
	}
	defer rows.Close()

	posters := make([]domain.PosterRecord, 0, limit)

	for rows.Next() {
		var poster domain.PosterRecord
		var selectedID sql.NullString
		var errorMessage sql.NullString
		var completedAt sql.NullString
		var createdAt string
		var updatedAt string

		if err := rows.Scan(
			&poster.ID,
			&poster.Status,
			&poster.StyleKey,
			&poster.EventJSON,
			&poster.BrandingJSON,
			&poster.VisualJSON,
			&poster.GoalJSON,
			&selectedID,
			&errorMessage,
			&createdAt,
			&updatedAt,
			&completedAt,
		); err != nil {
			return nil, fmt.Errorf(
				"scan active poster request: %w",
				err,
			)
		}

		poster.SelectedCandidateID = selectedID.String
		poster.ErrorMessage = errorMessage.String

		poster.CreatedAt, err = parseTime(createdAt)
		if err != nil {
			return nil, err
		}

		poster.UpdatedAt, err = parseTime(updatedAt)
		if err != nil {
			return nil, err
		}

		poster.CompletedAt, err = parseOptionalTime(completedAt)
		if err != nil {
			return nil, err
		}

		posters = append(posters, poster)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf(
			"iterate active poster requests: %w",
			err,
		)
	}

	return posters, nil
}

// MedianPosterDurationSeconds 返回历史上已成功海报的中位总耗时，用于 ETA。
//
// 样本不足时返回 ok=false —— 编一个进度估计比不给估计更糟，客户端宁可不显示
// ETA 也不该显示一个凭空来的数字。
func (r *Repository) MedianPosterDurationSeconds(
	ctx context.Context,
	minimumSamples int,
) (int, bool, error) {
	if minimumSamples < 1 {
		minimumSamples = 3
	}

	var count int

	if err := r.db.QueryRowContext(
		ctx,
		`
		SELECT COUNT(*)
		FROM poster_requests
		WHERE status = ?
		`,
		string(domain.PosterStatusSucceeded),
	).Scan(&count); err != nil {
		return 0, false, fmt.Errorf(
			"count succeeded posters: %w",
			err,
		)
	}

	if count < minimumSamples {
		return 0, false, nil
	}

	var median float64

	err := r.db.QueryRowContext(
		ctx,
		`
		SELECT duration
		FROM (
			SELECT
				(julianday(updated_at) - julianday(created_at))
					* 86400.0 AS duration
			FROM poster_requests
			WHERE status = ?
			ORDER BY duration
		)
		LIMIT 1
		OFFSET ?
		`,
		string(domain.PosterStatusSucceeded),
		count/2,
	).Scan(&median)
	if err != nil {
		return 0, false, fmt.Errorf(
			"median poster duration: %w",
			err,
		)
	}

	if median <= 0 {
		return 0, false, nil
	}

	return int(median), true, nil
}
