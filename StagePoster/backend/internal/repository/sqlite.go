package repository

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"

	_ "modernc.org/sqlite"
)

var ErrNotFound = errors.New("record not found")

type Repository struct {
	db *sql.DB
}

func OpenSQLite(
	ctx context.Context,
	path string,
) (*Repository, error) {
	if path == "" {
		return nil, errors.New("database path is required")
	}

	if err := os.MkdirAll(
		filepath.Dir(path),
		0o755,
	); err != nil {
		return nil, fmt.Errorf(
			"create database directory: %w",
			err,
		)
	}

	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}

	// SQLite MVP 阶段使用一个数据库连接，避免多连接 PRAGMA
	// 与单写入者模型带来的额外复杂度。
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	db.SetConnMaxLifetime(0)

	repository := &Repository{db: db}

	if err := repository.configure(ctx); err != nil {
		_ = db.Close()
		return nil, err
	}

	if err := repository.Migrate(ctx); err != nil {
		_ = db.Close()
		return nil, err
	}

	if err := repository.MigrateAssets(ctx); err != nil {
		_ = db.Close()
		return nil, err
	}

	if err := repository.MigratePosters(ctx); err != nil {
		_ = db.Close()
		return nil, err
	}

	if err := repository.MigratePosterOutputs(ctx); err != nil {
		_ = db.Close()
		return nil, err
	}
	if err := repository.MigrateReviews(ctx); err != nil {
		_ = db.Close()
		return nil, err
	}
	if err := repository.MigrateAISessions(ctx); err != nil {
		_ = db.Close()
		return nil, err
	}
	return repository, nil
}

func (r *Repository) configure(
	ctx context.Context,
) error {
	statements := []string{
		`PRAGMA foreign_keys = ON`,
		`PRAGMA journal_mode = WAL`,
		`PRAGMA busy_timeout = 5000`,
		`PRAGMA synchronous = NORMAL`,
	}

	for _, statement := range statements {
		if _, err := r.db.ExecContext(
			ctx,
			statement,
		); err != nil {
			return fmt.Errorf(
				"configure sqlite with %q: %w",
				statement,
				err,
			)
		}
	}

	if err := r.db.PingContext(ctx); err != nil {
		return fmt.Errorf("ping sqlite: %w", err)
	}

	return nil
}

func (r *Repository) Migrate(
	ctx context.Context,
) error {
	schema := []string{
		`
		CREATE TABLE IF NOT EXISTS jobs (
			id TEXT PRIMARY KEY,
			comfy_prompt_id TEXT UNIQUE,

			workflow_key TEXT NOT NULL,
			workflow_version TEXT NOT NULL,

			prompt TEXT NOT NULL,
			negative_prompt TEXT NOT NULL DEFAULT '',
			seed INTEGER NOT NULL,

			status TEXT NOT NULL,
			request_json TEXT NOT NULL DEFAULT '',
			error_message TEXT,

			created_at TEXT NOT NULL,
			started_at TEXT,
			completed_at TEXT,
			updated_at TEXT NOT NULL
		)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_jobs_status_created_at
		ON jobs(status, created_at DESC)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_jobs_created_at
		ON jobs(created_at DESC)
		`,
		`
		CREATE TABLE IF NOT EXISTS outputs (
			id TEXT PRIMARY KEY,
			job_id TEXT NOT NULL,

			kind TEXT NOT NULL,
			filename TEXT NOT NULL,
			mime_type TEXT NOT NULL,
			storage_path TEXT NOT NULL,

			width INTEGER NOT NULL DEFAULT 0,
			height INTEGER NOT NULL DEFAULT 0,

			created_at TEXT NOT NULL,

			FOREIGN KEY(job_id)
				REFERENCES jobs(id)
				ON DELETE CASCADE,

			UNIQUE(job_id, kind)
		)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_outputs_job_id
		ON outputs(job_id)
		`,
	}

	for _, statement := range schema {
		if _, err := r.db.ExecContext(
			ctx,
			statement,
		); err != nil {
			return fmt.Errorf(
				"run database migration: %w",
				err,
			)
		}
	}

	return nil
}

func (r *Repository) Close() error {
	return r.db.Close()
}

func (r *Repository) CreateJob(
	ctx context.Context,
	job domain.Job,
) error {
	now := time.Now().UTC()

	if job.CreatedAt.IsZero() {
		job.CreatedAt = now
	}

	if job.UpdatedAt.IsZero() {
		job.UpdatedAt = job.CreatedAt
	}

	if job.Status == "" {
		job.Status = domain.JobStatusQueued
	}

	_, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO jobs (
			id,
			comfy_prompt_id,
			workflow_key,
			workflow_version,
			prompt,
			negative_prompt,
			seed,
			status,
			request_json,
			error_message,
			created_at,
			started_at,
			completed_at,
			updated_at
		)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`,
		job.ID,
		nullableString(job.ComfyPromptID),
		job.WorkflowKey,
		job.WorkflowVersion,
		job.Prompt,
		job.NegativePrompt,
		job.Seed,
		job.Status,
		job.RequestJSON,
		nullableString(job.ErrorMessage),
		formatTime(job.CreatedAt),
		formatOptionalTime(job.StartedAt),
		formatOptionalTime(job.CompletedAt),
		formatTime(job.UpdatedAt),
	)
	if err != nil {
		return fmt.Errorf("insert job: %w", err)
	}

	return nil
}

func (r *Repository) MarkSubmitted(
	ctx context.Context,
	jobID string,
	comfyPromptID string,
	startedAt time.Time,
) error {
	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE jobs
		SET
			comfy_prompt_id = ?,
			status = ?,
			started_at = ?,
			updated_at = ?,
			error_message = NULL
		WHERE id = ?
		`,
		comfyPromptID,
		domain.JobStatusRunning,
		formatTime(startedAt),
		formatTime(startedAt),
		jobID,
	)
	if err != nil {
		return fmt.Errorf("mark job submitted: %w", err)
	}

	return requireAffected(result)
}

func (r *Repository) MarkFailed(
	ctx context.Context,
	jobID string,
	message string,
	completedAt time.Time,
) error {
	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE jobs
		SET
			status = ?,
			error_message = ?,
			completed_at = ?,
			updated_at = ?
		WHERE id = ?
		`,
		domain.JobStatusFailed,
		message,
		formatTime(completedAt),
		formatTime(completedAt),
		jobID,
	)
	if err != nil {
		return fmt.Errorf("mark job failed: %w", err)
	}

	return requireAffected(result)
}

func (r *Repository) MarkCanceled(
	ctx context.Context,
	jobID string,
	message string,
	completedAt time.Time,
) error {
	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE jobs
		SET
			status = ?,
			error_message = ?,
			completed_at = ?,
			updated_at = ?
		WHERE id = ?
		`,
		domain.JobStatusCanceled,
		message,
		formatTime(completedAt),
		formatTime(completedAt),
		jobID,
	)
	if err != nil {
		return fmt.Errorf("mark job canceled: %w", err)
	}

	return requireAffected(result)
}

func (r *Repository) CompleteJob(
	ctx context.Context,
	jobID string,
	output domain.Output,
	completedAt time.Time,
) error {
	transaction, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin complete-job transaction: %w", err)
	}

	defer func() {
		_ = transaction.Rollback()
	}()

	if output.ID == "" {
		output.ID, err = domain.NewID("out_")
		if err != nil {
			return err
		}
	}

	if output.CreatedAt.IsZero() {
		output.CreatedAt = completedAt
	}

	_, err = transaction.ExecContext(
		ctx,
		`
		INSERT INTO outputs (
			id,
			job_id,
			kind,
			filename,
			mime_type,
			storage_path,
			width,
			height,
			created_at
		)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(job_id, kind)
		DO UPDATE SET
			filename = excluded.filename,
			mime_type = excluded.mime_type,
			storage_path = excluded.storage_path,
			width = excluded.width,
			height = excluded.height,
			created_at = excluded.created_at
		`,
		output.ID,
		jobID,
		output.Kind,
		output.Filename,
		output.MimeType,
		output.StoragePath,
		output.Width,
		output.Height,
		formatTime(output.CreatedAt),
	)
	if err != nil {
		return fmt.Errorf("insert job output: %w", err)
	}

	result, err := transaction.ExecContext(
		ctx,
		`
		UPDATE jobs
		SET
			status = ?,
			completed_at = ?,
			updated_at = ?,
			error_message = NULL
		WHERE id = ?
		`,
		domain.JobStatusSucceeded,
		formatTime(completedAt),
		formatTime(completedAt),
		jobID,
	)
	if err != nil {
		return fmt.Errorf("complete job: %w", err)
	}

	if err := requireAffected(result); err != nil {
		return err
	}

	if err := transaction.Commit(); err != nil {
		return fmt.Errorf(
			"commit complete-job transaction: %w",
			err,
		)
	}

	return nil
}

func (r *Repository) GetJob(
	ctx context.Context,
	jobID string,
) (domain.Job, error) {
	row := r.db.QueryRowContext(
		ctx,
		`
		SELECT
			id,
			comfy_prompt_id,
			workflow_key,
			workflow_version,
			prompt,
			negative_prompt,
			seed,
			status,
			request_json,
			error_message,
			created_at,
			started_at,
			completed_at,
			updated_at
		FROM jobs
		WHERE id = ?
		`,
		jobID,
	)

	job, err := scanJob(row)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.Job{}, ErrNotFound
	}

	if err != nil {
		return domain.Job{}, fmt.Errorf("get job: %w", err)
	}

	return job, nil
}

// CountJobs 返回 jobs 表总行数，供列表信封的 total 用。
func (r *Repository) CountJobs(
	ctx context.Context,
) (int, error) {
	var total int

	if err := r.db.QueryRowContext(
		ctx,
		`SELECT COUNT(*) FROM jobs`,
	).Scan(&total); err != nil {
		return 0, fmt.Errorf("count jobs: %w", err)
	}

	return total, nil
}

func (r *Repository) ListJobs(
	ctx context.Context,
	page domain.Page,
) ([]domain.Job, error) {

	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			id,
			comfy_prompt_id,
			workflow_key,
			workflow_version,
			prompt,
			negative_prompt,
			seed,
			status,
			request_json,
			error_message,
			created_at,
			started_at,
			completed_at,
			updated_at
		FROM jobs
		ORDER BY created_at DESC
		LIMIT ? OFFSET ?
		`,
		page.Limit,
		page.Offset,
	)
	if err != nil {
		return nil, fmt.Errorf("list jobs: %w", err)
	}
	defer rows.Close()

	jobs := make([]domain.Job, 0, page.Limit)

	for rows.Next() {
		job, err := scanJob(rows)
		if err != nil {
			return nil, fmt.Errorf("scan listed job: %w", err)
		}

		jobs = append(jobs, job)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate jobs: %w", err)
	}

	return jobs, nil
}

func (r *Repository) ListActiveJobs(
	ctx context.Context,
	limit int,
) ([]domain.Job, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}

	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			id,
			comfy_prompt_id,
			workflow_key,
			workflow_version,
			prompt,
			negative_prompt,
			seed,
			status,
			request_json,
			error_message,
			created_at,
			started_at,
			completed_at,
			updated_at
		FROM jobs
		WHERE status IN (?, ?)
		ORDER BY created_at ASC
		LIMIT ?
		`,
		domain.JobStatusQueued,
		domain.JobStatusRunning,
		limit,
	)
	if err != nil {
		return nil, fmt.Errorf(
			"list active jobs: %w",
			err,
		)
	}
	defer rows.Close()

	jobs := make([]domain.Job, 0, limit)

	for rows.Next() {
		job, err := scanJob(rows)
		if err != nil {
			return nil, fmt.Errorf(
				"scan active job: %w",
				err,
			)
		}

		jobs = append(jobs, job)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf(
			"iterate active jobs: %w",
			err,
		)
	}

	return jobs, nil
}

func (r *Repository) GetOutput(
	ctx context.Context,
	jobID string,
	kind string,
) (domain.Output, error) {
	row := r.db.QueryRowContext(
		ctx,
		`
		SELECT
			id,
			job_id,
			kind,
			filename,
			mime_type,
			storage_path,
			width,
			height,
			created_at
		FROM outputs
		WHERE job_id = ? AND kind = ?
		`,
		jobID,
		kind,
	)

	var output domain.Output
	var createdAt string

	err := row.Scan(
		&output.ID,
		&output.JobID,
		&output.Kind,
		&output.Filename,
		&output.MimeType,
		&output.StoragePath,
		&output.Width,
		&output.Height,
		&createdAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.Output{}, ErrNotFound
	}

	if err != nil {
		return domain.Output{}, fmt.Errorf(
			"get output: %w",
			err,
		)
	}

	output.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.Output{}, err
	}

	return output, nil
}

type scanner interface {
	Scan(dest ...any) error
}

func scanJob(source scanner) (domain.Job, error) {
	var job domain.Job

	var comfyPromptID sql.NullString
	var errorMessage sql.NullString
	var startedAt sql.NullString
	var completedAt sql.NullString

	var createdAt string
	var updatedAt string

	err := source.Scan(
		&job.ID,
		&comfyPromptID,
		&job.WorkflowKey,
		&job.WorkflowVersion,
		&job.Prompt,
		&job.NegativePrompt,
		&job.Seed,
		&job.Status,
		&job.RequestJSON,
		&errorMessage,
		&createdAt,
		&startedAt,
		&completedAt,
		&updatedAt,
	)
	if err != nil {
		return domain.Job{}, err
	}

	job.ComfyPromptID = comfyPromptID.String
	job.ErrorMessage = errorMessage.String

	job.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.Job{}, err
	}

	job.UpdatedAt, err = parseTime(updatedAt)
	if err != nil {
		return domain.Job{}, err
	}

	job.StartedAt, err = parseOptionalTime(startedAt)
	if err != nil {
		return domain.Job{}, err
	}

	job.CompletedAt, err = parseOptionalTime(completedAt)
	if err != nil {
		return domain.Job{}, err
	}

	return job, nil
}

func nullableString(value string) any {
	if value == "" {
		return nil
	}

	return value
}

func formatTime(value time.Time) string {
	return value.UTC().Format(time.RFC3339Nano)
}

func formatOptionalTime(value *time.Time) any {
	if value == nil {
		return nil
	}

	return formatTime(*value)
}

func parseTime(value string) (time.Time, error) {
	parsed, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return time.Time{}, fmt.Errorf(
			"parse persisted time %q: %w",
			value,
			err,
		)
	}

	return parsed, nil
}

func parseOptionalTime(
	value sql.NullString,
) (*time.Time, error) {
	if !value.Valid || value.String == "" {
		return nil, nil
	}

	parsed, err := parseTime(value.String)
	if err != nil {
		return nil, err
	}

	return &parsed, nil
}

func requireAffected(result sql.Result) error {
	affected, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("read affected rows: %w", err)
	}

	if affected == 0 {
		return ErrNotFound
	}

	return nil
}

func (r *Repository) Ping(ctx context.Context) error {
	if err := r.db.PingContext(ctx); err != nil {
		return fmt.Errorf("ping repository database: %w", err)
	}

	return nil
}
