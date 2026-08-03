package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/comfy"
	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
	"github.com/Ripped-sys/StagePoster/backend/internal/repository"
	"github.com/Ripped-sys/StagePoster/backend/internal/storage"
)

var (
	ErrPromptRequired   = errors.New("prompt is required")
	ErrResultNotReady   = errors.New("result is not ready")
	ErrGenerationFailed = errors.New("generation failed")
)

type ResultFile struct {
	Body        io.ReadCloser
	Filename    string
	ContentType string
}

type PosterService struct {
	client          *comfy.Client
	template        *comfy.Template
	repository      *repository.Repository
	fileStore       *storage.FileStore
	workflowKey     string
	workflowVersion string
}

func NewPosterService(
	client *comfy.Client,
	template *comfy.Template,
	repositoryInstance *repository.Repository,
	fileStore *storage.FileStore,
	workflowKey string,
	workflowVersion string,
) *PosterService {
	return &PosterService{
		client:          client,
		template:        template,
		repository:      repositoryInstance,
		fileStore:       fileStore,
		workflowKey:     workflowKey,
		workflowVersion: workflowVersion,
	}
}

func (s *PosterService) Health(ctx context.Context) error {
	if err := s.repository.Ping(ctx); err != nil {
		return err
	}

	if err := s.client.Health(ctx); err != nil {
		return err
	}

	return nil
}

func (s *PosterService) ReleaseComfyMemory(
	ctx context.Context,
) error {
	const maxAttempts = 2

	var lastErr error

	for attempt := 1; attempt <= maxAttempts; attempt++ {
		if err := s.client.FreeMemory(ctx); err == nil {
			return nil
		} else {
			lastErr = err
		}

		if attempt == maxAttempts {
			break
		}

		timer := time.NewTimer(2 * time.Second)

		select {
		case <-ctx.Done():
			if !timer.Stop() {
				<-timer.C
			}

			return ctx.Err()

		case <-timer.C:
		}
	}

	return fmt.Errorf(
		"release ComfyUI memory after %d attempts: %w",
		maxAttempts,
		lastErr,
	)
}

func (s *PosterService) CancelPrompt(
	ctx context.Context,
	promptID string,
) error {
	return s.client.CancelPrompt(ctx, promptID)
}

func (s *PosterService) CancelJob(
	ctx context.Context,
	jobID string,
) error {
	job, err := s.repository.GetJob(ctx, jobID)
	if err != nil {
		return err
	}

	if job.Status == domain.JobStatusQueued ||
		job.Status == domain.JobStatusRunning {
		if job.ComfyPromptID != "" {
			_ = s.client.CancelPrompt(ctx, job.ComfyPromptID)
		}

		_ = s.repository.MarkCanceled(
			ctx,
			jobID,
			"cancelled by poster cancellation",
			time.Now().UTC(),
		)
	}

	return nil
}

func (s *PosterService) Bindings() comfy.Bindings {
	return s.template.Bindings()
}

func (s *PosterService) Generate(
	ctx context.Context,
	request domain.GenerateRequest,
) (domain.GenerateResponse, error) {
	request.Prompt = strings.TrimSpace(request.Prompt)
	request.NegativePrompt = strings.TrimSpace(
		request.NegativePrompt,
	)

	if request.Prompt == "" {
		return domain.GenerateResponse{}, ErrPromptRequired
	}

	seed := time.Now().UnixNano() & 0x7fffffffffffffff
	if request.Seed != nil {
		seed = *request.Seed
	}

	jobID, err := domain.NewID("job_")
	if err != nil {
		return domain.GenerateResponse{}, err
	}

	requestJSON, err := json.Marshal(request)
	if err != nil {
		return domain.GenerateResponse{}, fmt.Errorf(
			"marshal generation request: %w",
			err,
		)
	}

	now := time.Now().UTC()

	job := domain.Job{
		ID:              jobID,
		WorkflowKey:     s.workflowKey,
		WorkflowVersion: s.workflowVersion,
		Prompt:          request.Prompt,
		NegativePrompt:  request.NegativePrompt,
		Seed:            seed,
		Status:          domain.JobStatusQueued,
		RequestJSON:     string(requestJSON),
		CreatedAt:       now,
		UpdatedAt:       now,
	}

	if err := s.repository.CreateJob(ctx, job); err != nil {
		return domain.GenerateResponse{}, err
	}

	reference, err := s.resolveReferenceControl(ctx, request)
	if err != nil {
		s.failJob(ctx, jobID, err)
		return domain.GenerateResponse{}, err
	}

	workflow, err := s.template.Build(
		request.Prompt,
		request.NegativePrompt,
		seed,
		reference,
	)
	if err != nil {
		s.failJob(ctx, jobID, err)
		return domain.GenerateResponse{}, err
	}

	promptID, err := s.client.Submit(ctx, workflow)
	if err != nil {
		s.failJob(ctx, jobID, err)
		return domain.GenerateResponse{}, err
	}

	// 提交成功之后才落使用证据 —— 证据说的是"真的进了采样"。
	if reference.Requested() {
		s.recordReferenceUsage(
			ctx,
			request.ReferenceAssetID,
			reference.Strength,
		)
	}

	startedAt := time.Now().UTC()

	if err := s.repository.MarkSubmitted(
		ctx,
		jobID,
		promptID,
		startedAt,
	); err != nil {
		return domain.GenerateResponse{}, err
	}

	return domain.GenerateResponse{
		JobID:    jobID,
		PromptID: promptID,
		Status:   domain.JobStatusRunning,
		Seed:     seed,
	}, nil
}

func (s *PosterService) Status(
	ctx context.Context,
	jobID string,
) (domain.JobResponse, error) {
	job, err := s.repository.GetJob(ctx, jobID)
	if err != nil {
		return domain.JobResponse{}, err
	}

	if job.Status == domain.JobStatusQueued ||
		job.Status == domain.JobStatusRunning {
		if err := s.ReconcileJob(ctx, jobID); err != nil {
			return domain.JobResponse{}, err
		}

		job, err = s.repository.GetJob(ctx, jobID)
		if err != nil {
			return domain.JobResponse{}, err
		}
	}

	return s.jobResponse(ctx, job)
}

func (s *PosterService) ListJobs(
	ctx context.Context,
	page domain.Page,
) (domain.JobListResponse, error) {
	jobs, err := s.repository.ListJobs(ctx, page)
	if err != nil {
		return domain.JobListResponse{}, err
	}

	total, err := s.repository.CountJobs(ctx)
	if err != nil {
		return domain.JobListResponse{}, err
	}

	items := make([]domain.JobResponse, 0, len(jobs))

	for _, job := range jobs {
		response, err := s.jobResponse(ctx, job)
		if err != nil {
			return domain.JobListResponse{}, err
		}

		items = append(items, response)
	}

	return domain.JobListResponse{
		Items: items,
		ListMeta: domain.NewListMeta(
			page,
			len(items),
			total,
		),
	}, nil
}

func (s *PosterService) OpenResult(
	ctx context.Context,
	jobID string,
) (ResultFile, error) {
	job, err := s.repository.GetJob(ctx, jobID)
	if err != nil {
		return ResultFile{}, err
	}

	if job.Status == domain.JobStatusQueued ||
		job.Status == domain.JobStatusRunning {
		if err := s.ReconcileJob(ctx, jobID); err != nil {
			return ResultFile{}, err
		}

		job, err = s.repository.GetJob(ctx, jobID)
		if err != nil {
			return ResultFile{}, err
		}
	}

	if job.Status == domain.JobStatusFailed {
		return ResultFile{}, ErrGenerationFailed
	}

	output, err := s.repository.GetOutput(
		ctx,
		jobID,
		"poster",
	)
	if errors.Is(err, repository.ErrNotFound) {
		return ResultFile{}, ErrResultNotReady
	}

	if err != nil {
		return ResultFile{}, err
	}

	file, err := s.fileStore.Open(output)
	if err != nil {
		return ResultFile{}, err
	}

	return ResultFile{
		Body:        file,
		Filename:    output.Filename,
		ContentType: output.MimeType,
	}, nil
}

func (s *PosterService) ReconcileActiveJobs(
	ctx context.Context,
	limit int,
) error {
	jobs, err := s.repository.ListActiveJobs(ctx, limit)
	if err != nil {
		return err
	}

	var reconciliationErrors []error

	for _, job := range jobs {
		if err := s.ReconcileJob(ctx, job.ID); err != nil {
			reconciliationErrors = append(
				reconciliationErrors,
				fmt.Errorf(
					"reconcile %s: %w",
					job.ID,
					err,
				),
			)
		}
	}

	return errors.Join(reconciliationErrors...)
}

func (s *PosterService) ReconcileJob(
	ctx context.Context,
	jobID string,
) error {
	job, err := s.repository.GetJob(ctx, jobID)
	if err != nil {
		return err
	}

	switch job.Status {
	case domain.JobStatusSucceeded,
		domain.JobStatusFailed,
		domain.JobStatusCanceled:
		return nil
	}

	if job.ComfyPromptID == "" {
		if time.Since(job.CreatedAt) > 2*time.Minute {
			return s.repository.MarkFailed(
				ctx,
				jobID,
				"submission interrupted before ComfyUI accepted the job",
				time.Now().UTC(),
			)
		}

		return nil
	}

	status, image, messages, err := s.client.Inspect(
		ctx,
		job.ComfyPromptID,
	)
	if err != nil {
		return err
	}

	switch status {
	case "running":
		return nil

	case "failed":
		message := encodeMessages(messages)

		if message == "" {
			message = "ComfyUI generation failed"
		}

		return s.repository.MarkFailed(
			ctx,
			jobID,
			message,
			time.Now().UTC(),
		)

	case "succeeded":
		if image == nil {
			return s.repository.MarkFailed(
				ctx,
				jobID,
				"ComfyUI completed without an image output",
				time.Now().UTC(),
			)
		}

		existingOutput, outputErr :=
			s.repository.GetOutput(ctx, jobID, "poster")

		if outputErr == nil {
			return s.repository.CompleteJob(
				ctx,
				jobID,
				existingOutput,
				time.Now().UTC(),
			)
		}

		if !errors.Is(outputErr, repository.ErrNotFound) {
			return outputErr
		}

		response, err := s.client.OpenImage(ctx, *image)
		if err != nil {
			return err
		}
		defer response.Body.Close()

		output, err := s.fileStore.SavePoster(
			jobID,
			image.Filename,
			response.Header.Get("Content-Type"),
			response.Body,
		)
		if err != nil {
			return err
		}

		return s.repository.CompleteJob(
			ctx,
			jobID,
			output,
			time.Now().UTC(),
		)
	}

	return nil
}

func (s *PosterService) jobResponse(
	ctx context.Context,
	job domain.Job,
) (domain.JobResponse, error) {
	response := domain.JobResponse{
		JobID:           job.ID,
		PromptID:        job.ComfyPromptID,
		Status:          job.Status,
		Prompt:          job.Prompt,
		NegativePrompt:  job.NegativePrompt,
		Seed:            job.Seed,
		WorkflowKey:     job.WorkflowKey,
		WorkflowVersion: job.WorkflowVersion,
		Error:           job.ErrorMessage,
		CreatedAt:       job.CreatedAt,
		StartedAt:       job.StartedAt,
		CompletedAt:     job.CompletedAt,
		UpdatedAt:       job.UpdatedAt,
	}

	output, err := s.repository.GetOutput(
		ctx,
		job.ID,
		"poster",
	)
	if errors.Is(err, repository.ErrNotFound) {
		return response, nil
	}

	if err != nil {
		return domain.JobResponse{}, err
	}

	response.Image = &domain.ImageMeta{
		Filename:  output.Filename,
		Subfolder: "",
		Type:      "stored",
	}

	response.ResultURL =
		"/api/jobs/" + job.ID + "/result"

	return response, nil
}

func (s *PosterService) failJob(
	ctx context.Context,
	jobID string,
	cause error,
) {
	failContext, cancel := context.WithTimeout(
		context.Background(),
		5*time.Second,
	)
	defer cancel()

	_ = s.repository.MarkFailed(
		failContext,
		jobID,
		cause.Error(),
		time.Now().UTC(),
	)
}

func encodeMessages(messages []any) string {
	if len(messages) == 0 {
		return ""
	}

	raw, err := json.Marshal(messages)
	if err != nil {
		return fmt.Sprintf("%v", messages)
	}

	return string(raw)
}

// NegativePromptState 报告负向提示词是否真的会影响出图，以及生效所依赖的
// 采样器 cfg 和绑定节点。
//
// 负向词一直被算出来、存进库、在 API 里返回，但工作流没有负向文本节点、
// cfg 又是 1，提交给 ComfyUI 的图完全没受影响 —— 一个静默失效。
func (s *PosterService) NegativePromptState() (
	bool,
	float64,
	string,
) {
	if s.template == nil {
		return false, 0, ""
	}

	node := ""

	if binding := s.template.Bindings().NegativePrompt; binding != nil {
		node = binding.NodeID
	}

	return s.template.NegativePromptEffective(),
		s.template.EffectiveCFG(),
		node
}
