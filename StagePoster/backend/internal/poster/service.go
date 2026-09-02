package poster

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
	"github.com/Ripped-sys/StagePoster/backend/internal/repository"
	coreservice "github.com/Ripped-sys/StagePoster/backend/internal/service"
)

var (
	ErrInvalidPosterBrief    = errors.New("invalid poster brief")
	ErrCandidateNotReady     = errors.New("candidate is not ready")
	ErrPosterNotSelectable   = errors.New("poster is not awaiting candidate selection")
	ErrPosterSelectionLocked = errors.New("poster candidate selection is locked")
)

type Service struct {
	repository *repository.Repository
	core       *coreservice.PosterService
	planner    *Planner
	evaluator  *Evaluator
	composer   CompositionEngine

	reconcileMu sync.Mutex
	selectMu    sync.Mutex
}

func NewService(
	repositoryInstance *repository.Repository,
	core *coreservice.PosterService,
	planner *Planner,
	evaluator *Evaluator,
	compositionEngine CompositionEngine,
) *Service {
	return &Service{
		repository: repositoryInstance,
		core:       core,
		planner:    planner,
		evaluator:  evaluator,
		composer:   compositionEngine,
	}
}

func (s *Service) Create(
	ctx context.Context,
	request domain.CreatePosterRequest,
) (domain.PosterResponse, error) {
	request.Event.Title = strings.TrimSpace(
		request.Event.Title,
	)

	if request.Event.Title == "" {
		return domain.PosterResponse{},
			fmt.Errorf(
				"%w: event title is required",
				ErrInvalidPosterBrief,
			)
	}

	if strings.TrimSpace(request.Visual.Style) == "" {
		request.Visual.Style = "metal-gothic-v1"
	}

	specs, err := s.planner.Plan(request)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	if len(specs) != 3 {
		return domain.PosterResponse{},
			errors.New(
				"candidate planner must return exactly 3 candidates",
			)
	}

	posterID, err := domain.NewID("poster_")
	if err != nil {
		return domain.PosterResponse{}, err
	}

	goal := domain.GoalContract{
		Width:               1024,
		Height:              1536,
		AllowPeople:         false,
		AllowReadableText:   false,
		RequireCentralMotif: true,
		MaxAttempts:         2,
	}

	eventJSON, err := marshalJSON(request.Event)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	brandingJSON, err := marshalJSON(request.Branding)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	visualJSON, err := marshalJSON(request.Visual)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	goalJSON, err := marshalJSON(goal)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	now := time.Now().UTC()

	posterRecord := domain.PosterRecord{
		ID:           posterID,
		Status:       domain.PosterStatusPlanning,
		StyleKey:     request.Visual.Style,
		EventJSON:    eventJSON,
		BrandingJSON: brandingJSON,
		VisualJSON:   visualJSON,
		GoalJSON:     goalJSON,
		CreatedAt:    now,
		UpdatedAt:    now,
	}

	if err := s.repository.CreatePoster(
		ctx,
		posterRecord,
	); err != nil {
		return domain.PosterResponse{}, err
	}

	baseSeed := time.Now().UnixNano() &
		0x7fffffffffffffff

	for index, spec := range specs {
		compiledPrompt := s.planner.BuildPrompt(
			request,
			spec,
		)

		seed := baseSeed +
			int64((index+1)*100003)

		generation, err := s.core.Generate(
			ctx,
			applyReferenceControl(
				domain.GenerateRequest{
					Prompt: compiledPrompt,
					Seed:   &seed,
				},
				request.Visual,
			),
		)
		if err != nil {
			_ = s.repository.UpdatePosterStatus(
				context.Background(),
				posterID,
				domain.PosterStatusFailed,
				err.Error(),
			)

			return domain.PosterResponse{}, err
		}

		candidateID, err := domain.NewID("candidate_")
		if err != nil {
			return domain.PosterResponse{}, err
		}

		specJSON, err := marshalJSON(spec)
		if err != nil {
			return domain.PosterResponse{}, err
		}

		candidateNow := time.Now().UTC()

		candidate := domain.CandidateRecord{
			ID:             candidateID,
			PosterID:       posterID,
			JobID:          generation.JobID,
			VariantIndex:   index,
			VariantKey:     spec.VariantKey,
			VariantName:    spec.VariantName,
			SpecJSON:       specJSON,
			CompiledPrompt: compiledPrompt,
			Seed:           seed,
			Attempt:        1,
			Status:         domain.CandidateStatusGenerating,
			Passed:         false,
			Selected:       false,
			CreatedAt:      candidateNow,
			UpdatedAt:      candidateNow,
		}

		if err := s.repository.CreateCandidate(
			ctx,
			candidate,
		); err != nil {
			_ = s.repository.UpdatePosterStatus(
				context.Background(),
				posterID,
				domain.PosterStatusFailed,
				err.Error(),
			)

			return domain.PosterResponse{}, err
		}
	}

	if err := s.repository.UpdatePosterStatus(
		ctx,
		posterID,
		domain.PosterStatusGenerating,
		"",
	); err != nil {
		return domain.PosterResponse{}, err
	}

	return s.Get(ctx, posterID)
}

func (s *Service) Get(
	ctx context.Context,
	posterID string,
) (domain.PosterResponse, error) {
	if err := s.ReconcilePoster(
		ctx,
		posterID,
	); err != nil {
		return domain.PosterResponse{}, err
	}

	posterRecord, err := s.repository.GetPoster(
		ctx,
		posterID,
	)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	candidates, err := s.repository.ListCandidates(
		ctx,
		posterID,
	)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	response := domain.PosterResponse{
		PosterID:            posterRecord.ID,
		Status:              posterRecord.Status,
		SelectedCandidateID: posterRecord.SelectedCandidateID,
		Error:               posterRecord.ErrorMessage,
		CreatedAt:           posterRecord.CreatedAt,
		UpdatedAt:           posterRecord.UpdatedAt,
		Progress: domain.PosterProgress{
			Total: len(candidates),
			Stage: string(posterRecord.Status),
			Percent: domain.StageProgress(
				posterRecord.Status,
			),
			ElapsedSeconds: int(
				posterRecord.UpdatedAt.
					Sub(posterRecord.CreatedAt).
					Seconds(),
			),
		},
		Candidates: make(
			[]domain.CandidateResponse,
			0,
			len(candidates),
		),
	}

	for _, candidate := range candidates {
		item := domain.CandidateResponse{
			CandidateID: candidate.ID,
			VariantKey:  candidate.VariantKey,
			VariantName: candidate.VariantName,
			Status:      candidate.Status,
			Attempt:     candidate.Attempt,
			Selected:    candidate.Selected,
			Seed:        candidate.Seed,
			Error:       candidate.ErrorMessage,
		}

		if spec, ok := decodeCandidateSpec(
			candidate.SpecJSON,
		); ok {
			item.Spec = &spec
		}

		if candidate.Status == domain.CandidateStatusReady {
			item.ImageURL = fmt.Sprintf(
				"/api/posters/%s/candidates/%s/image",
				posterID,
				candidate.ID,
			)
		}

		if candidate.Status == domain.CandidateStatusReady ||
			candidate.Status == domain.CandidateStatusFailed {
			response.Progress.Completed++
		}

		response.Candidates = append(
			response.Candidates,
			item,
		)
	}

	if posterRecord.Status == domain.PosterStatusSucceeded {
		response.ResultURL = fmt.Sprintf(
			"/api/posters/%s/result",
			posterID,
		)
		response.ThumbnailURL = fmt.Sprintf(
			"/api/posters/%s/thumbnail",
			posterID,
		)
	}

	// ETA 只在任务还没结束、且历史样本够多时给。估计不出来就不给字段，
	// 而不是给 0 —— 客户端会把 0 当成"马上就好"。
	if !posterRecord.Status.Terminal() {
		median, ok, err := s.repository.
			MedianPosterDurationSeconds(ctx, 3)
		if err != nil {
			return domain.PosterResponse{}, err
		}

		if ok {
			remaining := median -
				response.Progress.ElapsedSeconds

			if remaining < 0 {
				remaining = 0
			}

			response.Progress.EtaSeconds = &remaining
		}
	}

	return response, nil
}

func (s *Service) Select(
	ctx context.Context,
	posterID string,
	candidateID string,
) (domain.PosterResponse, error) {
	posterID = strings.TrimSpace(posterID)
	candidateID = strings.TrimSpace(candidateID)

	if posterID == "" {
		return domain.PosterResponse{},
			repository.ErrNotFound
	}

	if candidateID == "" {
		return domain.PosterResponse{},
			ErrCandidateNotReady
	}

	// 将选择动作串行化，避免两个并发请求同时改变选中项，
	// 或重复触发 Composer。
	s.selectMu.Lock()
	defer s.selectMu.Unlock()

	if err := s.ReconcilePoster(
		ctx,
		posterID,
	); err != nil {
		return domain.PosterResponse{}, err
	}

	posterRecord, err := s.repository.GetPoster(
		ctx,
		posterID,
	)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	switch posterRecord.Status {
	case domain.PosterStatusSucceeded:
		// 完全相同的重复请求直接返回已有结果。
		if posterRecord.SelectedCandidateID != candidateID {
			return domain.PosterResponse{},
				fmt.Errorf(
					"%w: poster already completed with candidate %s",
					ErrPosterSelectionLocked,
					posterRecord.SelectedCandidateID,
				)
		}

		for _, kind := range []string{
			domain.PosterOutputKindFinal,
			domain.PosterOutputKindThumbnail,
		} {
			output, outputErr :=
				s.repository.GetPosterOutput(
					ctx,
					posterID,
					kind,
				)
			if outputErr != nil {
				if errors.Is(
					outputErr,
					repository.ErrNotFound,
				) {
					return domain.PosterResponse{},
						fmt.Errorf(
							"%w: missing %s output",
							ErrResultNotReady,
							kind,
						)
				}

				return domain.PosterResponse{},
					outputErr
			}

			if _, statErr := os.Stat(
				output.StoragePath,
			); statErr != nil {
				return domain.PosterResponse{},
					fmt.Errorf(
						"%w: %s: %v",
						ErrResultNotReady,
						kind,
						statErr,
					)
			}
		}

		return s.Get(ctx, posterID)

	case domain.PosterStatusSelected,
		domain.PosterStatusComposing:

		// 正在合成时，重复提交同一 Candidate 属于幂等请求。
		if posterRecord.SelectedCandidateID != candidateID {
			return domain.PosterResponse{},
				fmt.Errorf(
					"%w: poster is composing candidate %s",
					ErrPosterSelectionLocked,
					posterRecord.SelectedCandidateID,
				)
		}

		return s.Get(ctx, posterID)

	case domain.PosterStatusAwaitingSelection:
		// 合法的首次选择继续向下执行。

	default:
		return domain.PosterResponse{},
			fmt.Errorf(
				"%w: current status is %s",
				ErrPosterNotSelectable,
				posterRecord.Status,
			)
	}

	if err := s.repository.SelectCandidate(
		ctx,
		posterID,
		candidateID,
	); err != nil {
		return domain.PosterResponse{}, err
	}

	return s.Get(ctx, posterID)
}

func (s *Service) OpenCandidate(
	ctx context.Context,
	posterID string,
	candidateID string,
) (coreservice.ResultFile, error) {
	candidates, err := s.repository.ListCandidates(
		ctx,
		posterID,
	)
	if err != nil {
		return coreservice.ResultFile{}, err
	}

	for _, candidate := range candidates {
		if candidate.ID != candidateID {
			continue
		}

		if candidate.Status != domain.CandidateStatusReady ||
			!candidate.Passed {
			return coreservice.ResultFile{},
				ErrCandidateNotReady
		}

		return s.core.OpenResult(
			ctx,
			candidate.JobID,
		)
	}

	return coreservice.ResultFile{},
		repository.ErrNotFound
}

func (s *Service) ReconcileActive(
	ctx context.Context,
	limit int,
) error {
	posters, err := s.repository.ListActivePosters(
		ctx,
		limit,
	)
	if err != nil {
		return err
	}

	var reconciliationErrors []error

	for _, posterRecord := range posters {
		if err := s.ReconcilePoster(
			ctx,
			posterRecord.ID,
		); err != nil {
			reconciliationErrors = append(
				reconciliationErrors,
				fmt.Errorf(
					"reconcile poster %s: %w",
					posterRecord.ID,
					err,
				),
			)
		}
	}

	return errors.Join(reconciliationErrors...)
}

func (s *Service) ReconcilePoster(
	ctx context.Context,
	posterID string,
) error {
	s.reconcileMu.Lock()
	defer s.reconcileMu.Unlock()

	posterRecord, err := s.repository.GetPoster(
		ctx,
		posterID,
	)
	if err != nil {
		return err
	}

	switch posterRecord.Status {
	case domain.PosterStatusAwaitingSelection,
		domain.PosterStatusSucceeded,
		domain.PosterStatusFailed,
		domain.PosterStatusCanceled:
		return nil

	case domain.PosterStatusSelected,
		domain.PosterStatusComposing:
		return s.reconcileComposition(
			ctx,
			posterRecord,
		)

	case domain.PosterStatusPartialReady:
		// Continue reconciling remaining candidates below
	}

	var goal domain.GoalContract

	if err := json.Unmarshal(
		[]byte(posterRecord.GoalJSON),
		&goal,
	); err != nil {
		return fmt.Errorf(
			"decode poster goal contract: %w",
			err,
		)
	}

	candidates, err := s.repository.ListCandidates(
		ctx,
		posterID,
	)
	if err != nil {
		return err
	}

	if len(candidates) == 0 {
		if time.Since(posterRecord.CreatedAt) >
			2*time.Minute {
			return s.repository.UpdatePosterStatus(
				ctx,
				posterID,
				domain.PosterStatusFailed,
				"poster creation was interrupted before candidates were created",
			)
		}

		return nil
	}

	for _, candidate := range candidates {
		switch candidate.Status {
		case domain.CandidateStatusReady,
			domain.CandidateStatusFailed:
			continue
		}

		job, err := s.core.Status(
			ctx,
			candidate.JobID,
		)
		if err != nil {
			return err
		}

		switch job.Status {
		case domain.JobStatusQueued,
			domain.JobStatusRunning:
			continue

		case domain.JobStatusSucceeded:
			output, err := s.repository.GetOutput(
				ctx,
				candidate.JobID,
				"poster",
			)
			if err != nil {
				return err
			}

			if err := s.evaluator.Evaluate(
				output,
				goal,
			); err != nil {
				if retryErr := s.retryCandidate(
					ctx,
					candidate,
					goal,
					err.Error(),
				); retryErr != nil {
					return retryErr
				}

				continue
			}

			if err := s.repository.UpdateCandidateState(
				ctx,
				candidate.ID,
				domain.CandidateStatusReady,
				true,
				"",
			); err != nil {
				return err
			}

		case domain.JobStatusFailed,
			domain.JobStatusCanceled:
			if err := s.retryCandidate(
				ctx,
				candidate,
				goal,
				job.Error,
			); err != nil {
				return err
			}
		}
	}

	candidates, err = s.repository.ListCandidates(
		ctx,
		posterID,
	)
	if err != nil {
		return err
	}

	readyCount := 0
	failedCount := 0

	for _, candidate := range candidates {
		switch candidate.Status {
		case domain.CandidateStatusReady:
			readyCount++

		case domain.CandidateStatusFailed:
			failedCount++
		}
	}

	switch {
	case readyCount == len(candidates):
		if err := s.repository.UpdatePosterStatus(
			ctx,
			posterID,
			domain.PosterStatusAwaitingSelection,
			"",
		); err != nil {
			return err
		}

		// Candidate 文件已经持久化到本地。
		// 释放 ComfyUI 失败不能破坏成功的业务结果。
		releaseContext, cancel :=
			context.WithTimeout(
				context.Background(),
				45*time.Second,
			)

		releaseErr :=
			s.core.ReleaseComfyMemory(
				releaseContext,
			)

		cancel()

		if releaseErr != nil {
			log.Printf(
				"poster %s candidates ready, but ComfyUI memory release failed: %v",
				posterID,
				releaseErr,
			)
		}

		return nil

	case readyCount > 0:
		// 部分候选就绪，前端可立即查看已完成的候选图。
		if err := s.repository.UpdatePosterStatus(
			ctx,
			posterID,
			domain.PosterStatusPartialReady,
			"",
		); err != nil {
			return err
		}

		return nil

	case readyCount+failedCount == len(candidates) &&
		failedCount > 0:
		return s.repository.UpdatePosterStatus(
			ctx,
			posterID,
			domain.PosterStatusFailed,
			"one or more candidates failed after all retry attempts",
		)

	default:
		return s.repository.UpdatePosterStatus(
			ctx,
			posterID,
			domain.PosterStatusGenerating,
			"",
		)
	}
}

func (s *Service) retryCandidate(
	ctx context.Context,
	candidate domain.CandidateRecord,
	goal domain.GoalContract,
	reason string,
) error {
	if candidate.Attempt >= goal.MaxAttempts {
		return s.repository.UpdateCandidateState(
			ctx,
			candidate.ID,
			domain.CandidateStatusFailed,
			false,
			reason,
		)
	}

	nextAttempt := candidate.Attempt + 1

	nextSeed := candidate.Seed +
		int64(nextAttempt*104729)

	generation, err := s.core.Generate(
		ctx,
		domain.GenerateRequest{
			Prompt: candidate.CompiledPrompt,
			Seed:   &nextSeed,
		},
	)
	if err != nil {
		return s.repository.UpdateCandidateState(
			ctx,
			candidate.ID,
			domain.CandidateStatusFailed,
			false,
			err.Error(),
		)
	}

	return s.repository.ReplaceCandidateJob(
		ctx,
		candidate.ID,
		generation.JobID,
		nextSeed,
		nextAttempt,
	)
}

func (s *Service) Cancel(
	ctx context.Context,
	posterID string,
) error {
	posterID = strings.TrimSpace(posterID)

	if posterID == "" {
		return repository.ErrNotFound
	}

	s.reconcileMu.Lock()
	defer s.reconcileMu.Unlock()

	posterRecord, err := s.repository.GetPoster(
		ctx,
		posterID,
	)
	if err != nil {
		return err
	}

	switch posterRecord.Status {
	case domain.PosterStatusSucceeded,
		domain.PosterStatusFailed,
		domain.PosterStatusCanceled:
		return nil
	}

	candidates, err := s.repository.ListCandidates(
		ctx,
		posterID,
	)
	if err != nil {
		return err
	}

	for _, candidate := range candidates {
		if candidate.JobID != "" {
			job, jobErr := s.core.Status(ctx, candidate.JobID)
			if jobErr == nil && job.PromptID != "" {
				_ = s.core.CancelPrompt(ctx, job.PromptID)
			}

			_ = s.core.CancelJob(ctx, candidate.JobID)
		}
	}

	_ = s.core.ReleaseComfyMemory(ctx)

	return s.repository.UpdatePosterStatus(
		ctx,
		posterID,
		domain.PosterStatusCanceled,
		"cancelled by user",
	)
}

func (s *Service) RetryCandidate(
	ctx context.Context,
	posterID string,
	candidateID string,
) (domain.PosterResponse, error) {
	posterID = strings.TrimSpace(posterID)
	candidateID = strings.TrimSpace(candidateID)

	if posterID == "" || candidateID == "" {
		return domain.PosterResponse{}, repository.ErrNotFound
	}

	s.reconcileMu.Lock()
	defer s.reconcileMu.Unlock()

	posterRecord, err := s.repository.GetPoster(
		ctx,
		posterID,
	)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	switch posterRecord.Status {
	case domain.PosterStatusAwaitingSelection,
		domain.PosterStatusPartialReady,
		domain.PosterStatusGenerating:
		// 允许重试

	case domain.PosterStatusSucceeded,
		domain.PosterStatusFailed,
		domain.PosterStatusCanceled:
		return domain.PosterResponse{},
			fmt.Errorf(
				"%w: cannot retry candidate for %s poster",
				ErrPosterNotSelectable,
				posterRecord.Status,
			)

	default:
		return domain.PosterResponse{},
			fmt.Errorf(
				"%w: current status is %s",
				ErrPosterNotSelectable,
				posterRecord.Status,
			)
	}

	candidate, err := s.repository.GetCandidate(
		ctx,
		posterID,
		candidateID,
	)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	if candidate.Status != domain.CandidateStatusFailed {
		return domain.PosterResponse{},
			fmt.Errorf(
				"%w: candidate is not failed",
				ErrCandidateNotReady,
			)
	}

	var goal domain.GoalContract

	if err := json.Unmarshal(
		[]byte(posterRecord.GoalJSON),
		&goal,
	); err != nil {
		return domain.PosterResponse{}, fmt.Errorf(
			"decode poster goal contract: %w",
			err,
		)
	}

	retryErr := s.retryCandidate(
		ctx,
		candidate,
		goal,
		candidate.ErrorMessage,
	)
	if retryErr != nil {
		return domain.PosterResponse{}, retryErr
	}

	_ = s.repository.UpdatePosterStatus(
		ctx,
		posterID,
		domain.PosterStatusGenerating,
		"",
	)

	return s.Get(ctx, posterID)
}

func marshalJSON(value any) (string, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return "", fmt.Errorf(
			"marshal poster data: %w",
			err,
		)
	}

	return string(raw), nil
}

// decodeCandidateSpec 把落库的 spec JSON 还原成结构体，供 API 响应使用。
// 历史记录可能为空或格式不兼容，这类情况静默跳过而不是让整个查询失败。
func decodeCandidateSpec(
	raw string,
) (domain.CandidateSpec, bool) {
	if strings.TrimSpace(raw) == "" {
		return domain.CandidateSpec{}, false
	}

	var spec domain.CandidateSpec

	if err := json.Unmarshal(
		[]byte(raw),
		&spec,
	); err != nil {
		return domain.CandidateSpec{}, false
	}

	return spec, true
}
