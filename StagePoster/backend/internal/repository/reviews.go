package repository

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func (r *Repository) MigrateReviews(
	ctx context.Context,
) error {
	statements := []string{
		`
		CREATE TABLE IF NOT EXISTS poster_reviews (
			id TEXT PRIMARY KEY,
			poster_id TEXT NOT NULL,
			output_id TEXT NOT NULL,
			candidate_id TEXT,

			round INTEGER NOT NULL,
			total_score INTEGER NOT NULL,
			decision TEXT NOT NULL,
			result_json TEXT NOT NULL,

			model TEXT NOT NULL,
			prompt_tokens INTEGER NOT NULL DEFAULT 0,
			completion_tokens INTEGER NOT NULL DEFAULT 0,
			latency_ms INTEGER NOT NULL DEFAULT 0,

			created_at TEXT NOT NULL,

			FOREIGN KEY(poster_id)
				REFERENCES poster_requests(id)
				ON DELETE CASCADE,

			FOREIGN KEY(output_id)
				REFERENCES poster_outputs(id)
				ON DELETE CASCADE,

			FOREIGN KEY(candidate_id)
				REFERENCES poster_candidates(id),

			UNIQUE(poster_id, round)
		)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_poster_reviews_poster
		ON poster_reviews(poster_id, round DESC)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_poster_reviews_decision
		ON poster_reviews(decision, created_at DESC)
		`,
	}

	for _, statement := range statements {
		if _, err := r.db.ExecContext(
			ctx,
			statement,
		); err != nil {
			return fmt.Errorf(
				"run poster review migration: %w",
				err,
			)
		}
	}

	return nil
}

func (r *Repository) NextPosterReviewRound(
	ctx context.Context,
	posterID string,
) (int, error) {
	var round int

	err := r.db.QueryRowContext(
		ctx,
		`
		SELECT COALESCE(MAX(round), 0) + 1
		FROM poster_reviews
		WHERE poster_id = ?
		`,
		posterID,
	).Scan(&round)
	if err != nil {
		return 0, fmt.Errorf(
			"read next poster review round: %w",
			err,
		)
	}

	return round, nil
}

func (r *Repository) CreatePosterReview(
	ctx context.Context,
	review domain.PosterReviewRecord,
) error {
	if review.CreatedAt.IsZero() {
		review.CreatedAt = time.Now().UTC()
	}

	resultJSON, err := json.Marshal(review.Result)
	if err != nil {
		return fmt.Errorf(
			"encode poster review result: %w",
			err,
		)
	}

	_, err = r.db.ExecContext(
		ctx,
		`
		INSERT INTO poster_reviews (
			id,
			poster_id,
			output_id,
			candidate_id,
			round,
			total_score,
			decision,
			result_json,
			model,
			prompt_tokens,
			completion_tokens,
			latency_ms,
			created_at
		)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`,
		review.ID,
		review.PosterID,
		review.OutputID,
		nullableString(review.CandidateID),
		review.Round,
		review.TotalScore.Int(),
		review.Decision,
		string(resultJSON),
		review.Model,
		review.PromptTokens,
		review.CompletionTokens,
		review.LatencyMS,
		formatTime(review.CreatedAt),
	)
	if err != nil {
		return fmt.Errorf(
			"insert poster review: %w",
			err,
		)
	}

	return nil
}

// CountPosterReviews 返回某张海报的复审总轮数。
func (r *Repository) CountPosterReviews(
	ctx context.Context,
	posterID string,
) (int, error) {
	var total int

	if err := r.db.QueryRowContext(
		ctx,
		`
		SELECT COUNT(*)
		FROM poster_reviews
		WHERE poster_id = ?
		`,
		posterID,
	).Scan(&total); err != nil {
		return 0, fmt.Errorf(
			"count poster reviews: %w",
			err,
		)
	}

	return total, nil
}

func (r *Repository) ListPosterReviews(
	ctx context.Context,
	posterID string,
	page domain.Page,
) ([]domain.PosterReviewRecord, error) {

	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			id,
			poster_id,
			output_id,
			candidate_id,
			round,
			total_score,
			decision,
			result_json,
			model,
			prompt_tokens,
			completion_tokens,
			latency_ms,
			created_at
		FROM poster_reviews
		WHERE poster_id = ?
		ORDER BY round DESC
		LIMIT ? OFFSET ?
		`,
		posterID,
		page.Limit,
		page.Offset,
	)
	if err != nil {
		return nil, fmt.Errorf(
			"list poster reviews: %w",
			err,
		)
	}
	defer rows.Close()

	reviews := make(
		[]domain.PosterReviewRecord,
		0,
		page.Limit,
	)

	for rows.Next() {
		review, err := scanPosterReview(rows)
		if err != nil {
			return nil, err
		}

		reviews = append(reviews, review)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf(
			"iterate poster reviews: %w",
			err,
		)
	}

	return reviews, nil
}

func (r *Repository) GetPosterReview(
	ctx context.Context,
	reviewID string,
) (domain.PosterReviewRecord, error) {
	row := r.db.QueryRowContext(
		ctx,
		`
		SELECT
			id,
			poster_id,
			output_id,
			candidate_id,
			round,
			total_score,
			decision,
			result_json,
			model,
			prompt_tokens,
			completion_tokens,
			latency_ms,
			created_at
		FROM poster_reviews
		WHERE id = ?
		`,
		reviewID,
	)

	review, err := scanPosterReview(row)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.PosterReviewRecord{},
			ErrNotFound
	}

	if err != nil {
		return domain.PosterReviewRecord{},
			fmt.Errorf(
				"get poster review: %w",
				err,
			)
	}

	return review, nil
}

func scanPosterReview(
	source scanner,
) (domain.PosterReviewRecord, error) {
	var review domain.PosterReviewRecord

	var candidateID sql.NullString
	var totalScore int
	var decision string
	var resultJSON string
	var createdAt string

	err := source.Scan(
		&review.ID,
		&review.PosterID,
		&review.OutputID,
		&candidateID,
		&review.Round,
		&totalScore,
		&decision,
		&resultJSON,
		&review.Model,
		&review.PromptTokens,
		&review.CompletionTokens,
		&review.LatencyMS,
		&createdAt,
	)
	if err != nil {
		return domain.PosterReviewRecord{}, err
	}

	review.CandidateID = candidateID.String
	review.TotalScore = domain.Score(totalScore)
	review.Decision = domain.ReviewDecision(decision)

	if err := json.Unmarshal(
		[]byte(resultJSON),
		&review.Result,
	); err != nil {
		return domain.PosterReviewRecord{},
			fmt.Errorf(
				"decode poster review result: %w",
				err,
			)
	}

	// 数据库列是最终可信值，防止历史 JSON 与索引列不一致。
	review.Result.TotalScore = review.TotalScore
	review.Result.Decision = review.Decision

	review.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.PosterReviewRecord{}, err
	}

	return review, nil
}

// AggregatePosterReviewMetrics 汇总一张海报所有复审轮次的 token 与耗时。
//
// 每轮的 model / prompt_tokens / completion_tokens / latency_ms 一直在写库，
// 但没有任何地方把它们加起来 —— AIMetricsResponse 的作用域只有单次 LLM 调用，
// 想知道"这张海报一共烧了多少"完全无从查起。
func (r *Repository) AggregatePosterReviewMetrics(
	ctx context.Context,
	posterID string,
) (domain.PosterMetrics, error) {
	var metrics domain.PosterMetrics

	var promptTokens sql.NullInt64
	var completionTokens sql.NullInt64
	var latencyMS sql.NullInt64
	var rounds sql.NullInt64

	err := r.db.QueryRowContext(
		ctx,
		`
		SELECT
			COUNT(*),
			SUM(prompt_tokens),
			SUM(completion_tokens),
			SUM(latency_ms)
		FROM poster_reviews
		WHERE poster_id = ?
		`,
		posterID,
	).Scan(
		&rounds,
		&promptTokens,
		&completionTokens,
		&latencyMS,
	)
	if err != nil {
		return domain.PosterMetrics{}, fmt.Errorf(
			"aggregate poster review metrics: %w",
			err,
		)
	}

	metrics.ReviewRounds = int(rounds.Int64)
	metrics.PromptTokens = int(promptTokens.Int64)
	metrics.CompletionTokens = int(completionTokens.Int64)
	metrics.ReviewLatencyMS = latencyMS.Int64

	metrics.TotalTokens = metrics.PromptTokens +
		metrics.CompletionTokens

	return metrics, nil
}
