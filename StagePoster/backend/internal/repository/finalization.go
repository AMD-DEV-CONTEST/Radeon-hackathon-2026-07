package repository

import (
	"context"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func (r *Repository) AdoptCandidateJob(
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
			passed = 1,
			error_message = NULL,
			updated_at = ?
		WHERE id = ?
		`,
		jobID,
		seed,
		attempt,
		domain.CandidateStatusReady,
		formatTime(time.Now().UTC()),
		candidateID,
	)
	if err != nil {
		return err
	}

	return requireAffected(result)
}
