package assistant

import (
	"context"
	"errors"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
	posterflow "github.com/Ripped-sys/StagePoster/backend/internal/poster"
)

const maxFinalizeReviewRounds = 2

var (
	ErrFinalizeNotReady = errors.New(
		"AI session is not ready to finalize",
	)

	finalizeLocks keyedLock
)

func (s *Service) Finalize(
	ctx context.Context,
	sessionID string,
) (domain.AISessionResponse, error) {
	sessionID = strings.TrimSpace(sessionID)

	unlock := finalizeLocks.Lock(sessionID)
	defer unlock()

	session, err := s.repository.GetAISession(
		ctx,
		sessionID,
	)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	if session.PosterID == "" {
		return domain.AISessionResponse{},
			fmt.Errorf(
				"%w: session has no poster",
				ErrFinalizeNotReady,
			)
	}

	if session.Status ==
		domain.AISessionStatusCompletedWithWarnings {
		return s.Get(ctx, session.ID)
	}

	switch session.Status {
	case domain.AISessionStatusSucceeded:
		// 合成已完成，可以进入质量闭环。

	case domain.AISessionStatusFailed,
		domain.AISessionStatusCanceled:
		return domain.AISessionResponse{},
			ErrSessionTerminal

	default:
		return domain.AISessionResponse{},
			fmt.Errorf(
				"%w: current status is %s",
				ErrFinalizeNotReady,
				session.Status,
			)
	}

	planRecord, err := s.repository.GetAIDesignPlan(
		ctx,
		session.ID,
		session.SelectedPlanID,
	)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	for {
		reviews, _, err := s.posterFlow.ListReviews(
			ctx,
			session.PosterID,
			domain.NormalizePage(
				domain.MaxPageLimit,
				0,
			),
		)
		if err != nil {
			return domain.AISessionResponse{}, err
		}

		reviews = orderedReviews(reviews)

		if len(reviews) == 0 {
			review, reviewErr := s.executeFinalReview(
				ctx,
				session,
				&planRecord.Plan,
			)
			if reviewErr != nil {
				return domain.AISessionResponse{},
					reviewErr
			}

			if snapshotErr :=
				s.posterFlow.SnapshotReviewRound(
					ctx,
					session.PosterID,
					review.Round,
				); snapshotErr != nil {
				return domain.AISessionResponse{},
					snapshotErr
			}

			continue
		}

		latest := reviews[len(reviews)-1]

		if latest.Decision ==
			domain.ReviewDecisionAccept {
			if err := s.completeFinalization(
				ctx,
				&session,
				domain.AISessionStatusSucceeded,
				fmt.Sprintf(
					"视觉审查通过，最终评分 %d。",
					latest.TotalScore.Int(),
				),
			); err != nil {
				return domain.AISessionResponse{}, err
			}

			return s.Get(ctx, session.ID)
		}

		if latest.Round >= maxFinalizeReviewRounds {
			if err := s.finalizeBestAvailable(
				ctx,
				&session,
				reviews,
				"达到最大审查轮数，已保留评分最高的版本。",
			); err != nil {
				return domain.AISessionResponse{}, err
			}

			return s.Get(ctx, session.ID)
		}

		material, err :=
			s.posterFlow.ReviewMaterial(
				ctx,
				session.PosterID,
			)
		if err != nil {
			return domain.AISessionResponse{}, err
		}

		// Output 的 created_at 晚于 Review，说明该轮指令已经执行，
		// 但下一轮 Review 尚未写入。这样重试不会重复改图。
		if material.Output.CreatedAt.After(
			latest.CreatedAt,
		) {
			review, reviewErr := s.executeFinalReview(
				ctx,
				session,
				&planRecord.Plan,
			)
			if reviewErr != nil {
				return domain.AISessionResponse{},
					reviewErr
			}

			if snapshotErr :=
				s.posterFlow.SnapshotReviewRound(
					ctx,
					session.PosterID,
					review.Round,
				); snapshotErr != nil {
				return domain.AISessionResponse{},
					snapshotErr
			}

			continue
		}

		if err := s.posterFlow.SnapshotReviewRound(
			ctx,
			session.PosterID,
			latest.Round,
		); err != nil {
			return domain.AISessionResponse{}, err
		}

		var actionErr error

		switch latest.Decision {
		case domain.ReviewDecisionRecompose:
			// 如果算出来的版式和已经生效的完全一样，重排必然产出同一张图，
			// VLM 也必然给同一个分 —— 烧掉一轮换不到任何东西。
			// 直接收敛到当前最佳版本。
			if posterflow.ReviewAdjustmentsAreNoOp(
				latest.Result,
				latest.Round,
			) {
				if err := s.finalizeBestAvailable(
					ctx,
					&session,
					reviews,
					"重排不会改变版式，已保留评分最高的版本。",
				); err != nil {
					return domain.AISessionResponse{}, err
				}

				return s.Get(ctx, session.ID)
			}

			actionErr =
				s.posterFlow.RecomposeFromReview(
					ctx,
					session.PosterID,
					latest.Result,
					latest.Round,
				)

		case domain.ReviewDecisionRegenerate:
			if err := s.aiRuntime.Suspend(
				ctx,
			); err != nil {
				actionErr = err
				break
			}

			actionErr =
				s.posterFlow.RegenerateFromReview(
					ctx,
					session.PosterID,
					latest.Result,
					latest.Round,
				)

		case domain.ReviewDecisionRewriteBrief:
			session.Status =
				domain.AISessionStatusNeedsUserInput
			session.ErrorMessage = ""

			if err := s.repository.UpdateAISession(
				ctx,
				session,
			); err != nil {
				return domain.AISessionResponse{}, err
			}

			s.addFinalizeMessage(
				ctx,
				session.ID,
				"视觉方向存在冲突，需要补充或修改创意需求。",
			)

			return s.Get(ctx, session.ID)

		default:
			actionErr = fmt.Errorf(
				"unsupported review decision %s",
				latest.Decision,
			)
		}

		if actionErr != nil {
			if err := s.posterFlow.KeepExistingResult(
				ctx,
				session.PosterID,
			); err != nil {
				return domain.AISessionResponse{},
					errors.Join(actionErr, err)
			}

			if err := s.completeFinalization(
				ctx,
				&session,
				domain.AISessionStatusCompletedWithWarnings,
				"自动优化未能继续，已安全保留当前最佳版本。",
			); err != nil {
				return domain.AISessionResponse{},
					errors.Join(actionErr, err)
			}

			return s.Get(ctx, session.ID)
		}
	}
}

func (s *Service) executeFinalReview(
	ctx context.Context,
	session domain.AISessionRecord,
	designPlan *domain.DesignPlan,
) (domain.PosterReviewRecord, error) {
	material, err := s.posterFlow.ReviewMaterial(
		ctx,
		session.PosterID,
	)
	if err != nil {
		return domain.PosterReviewRecord{}, err
	}

	release, err := s.aiRuntime.Acquire(ctx)
	if err != nil {
		return domain.PosterReviewRecord{},
			fmt.Errorf(
				"acquire VLM for final review: %w",
				err,
			)
	}

	result, metrics, reviewErr :=
		s.aiService.Review(
			ctx,
			material.Output.StoragePath,
			session.Brief.Event,
			session.Brief.Visual,
			designPlan,
		)

	release()

	if reviewErr != nil {
		return domain.PosterReviewRecord{},
			reviewErr
	}

	round, err := s.posterFlow.NextReviewRound(
		ctx,
		session.PosterID,
	)
	if err != nil {
		return domain.PosterReviewRecord{}, err
	}

	reviewID, err := domain.NewID("review_")
	if err != nil {
		return domain.PosterReviewRecord{}, err
	}

	candidateID := material.Output.CandidateID

	if candidateID == "" &&
		material.Candidate != nil {
		candidateID = material.Candidate.ID
	}

	model := strings.TrimSpace(
		os.Getenv("VLM_MODEL"),
	)
	if model == "" {
		model = "stageposter-vlm"
	}

	review := domain.PosterReviewRecord{
		ID:          reviewID,
		PosterID:    session.PosterID,
		OutputID:    material.Output.ID,
		CandidateID: candidateID,
		Round:       round,
		TotalScore:  result.TotalScore,
		Decision:    result.Decision,
		Result:      result,
		Model:       model,

		PromptTokens:     metrics.PromptTokens,
		CompletionTokens: metrics.CompletionTokens,
		LatencyMS:        metrics.Latency.Milliseconds(),
		CreatedAt:        time.Now().UTC(),
	}

	if err := s.posterFlow.SaveReview(
		ctx,
		review,
	); err != nil {
		return domain.PosterReviewRecord{}, err
	}

	return review, nil
}

func (s *Service) finalizeBestAvailable(
	ctx context.Context,
	session *domain.AISessionRecord,
	reviews []domain.PosterReviewRecord,
	message string,
) error {
	latest := reviews[len(reviews)-1]

	if err := s.posterFlow.SnapshotReviewRound(
		ctx,
		session.PosterID,
		latest.Round,
	); err != nil {
		return err
	}

	best, found := bestReview(reviews)

	if found {
		if err := s.posterFlow.RestoreReviewRound(
			ctx,
			session.PosterID,
			best.Round,
		); err != nil {
			if !errors.Is(
				err,
				posterflow.ErrReviewSnapshotNotFound,
			) {
				return err
			}

			if keepErr :=
				s.posterFlow.KeepExistingResult(
					ctx,
					session.PosterID,
				); keepErr != nil {
				return errors.Join(err, keepErr)
			}
		}
	}

	return s.completeFinalization(
		ctx,
		session,
		domain.AISessionStatusCompletedWithWarnings,
		message,
	)
}

func (s *Service) completeFinalization(
	ctx context.Context,
	session *domain.AISessionRecord,
	status domain.AISessionStatus,
	message string,
) error {
	session.Status = status
	session.ErrorMessage = ""

	if err := s.repository.UpdateAISession(
		ctx,
		*session,
	); err != nil {
		return err
	}

	s.addFinalizeMessage(
		ctx,
		session.ID,
		message,
	)

	return nil
}

func (s *Service) addFinalizeMessage(
	ctx context.Context,
	sessionID string,
	content string,
) {
	messageID, err := domain.NewID("message_")
	if err != nil {
		return
	}

	_ = s.repository.CreateAIMessage(
		ctx,
		domain.AIMessageRecord{
			ID:        messageID,
			SessionID: sessionID,
			Role:      domain.AIMessageRoleSystem,
			Content:   content,
			CreatedAt: time.Now().UTC(),
		},
	)
}

func buildReviewSummary(
	reviews []domain.PosterReviewRecord,
	status domain.AISessionStatus,
) *domain.AIReviewSummary {
	reviews = orderedReviews(reviews)

	if len(reviews) == 0 &&
		status !=
			domain.AISessionStatusCompletedWithWarnings {
		return nil
	}

	summary := &domain.AIReviewSummary{
		Rounds: len(reviews),
	}

	if len(reviews) > 0 {
		latest := reviews[len(reviews)-1]
		summary.LatestDecision =
			latest.Decision
		summary.Accepted =
			latest.Decision ==
				domain.ReviewDecisionAccept

		best, found := bestReview(reviews)
		if found {
			summary.BestRound = best.Round
			summary.BestScore = best.TotalScore
		}
	}

	summary.Finalized =
		summary.Accepted ||
			status ==
				domain.AISessionStatusCompletedWithWarnings

	if status ==
		domain.AISessionStatusCompletedWithWarnings {
		summary.Warning =
			"Maximum review rounds reached or automatic optimization stopped; the best available version was retained."
	}

	return summary
}

func bestReview(
	reviews []domain.PosterReviewRecord,
) (domain.PosterReviewRecord, bool) {
	if len(reviews) == 0 {
		return domain.PosterReviewRecord{}, false
	}

	best := reviews[0]

	for _, review := range reviews[1:] {
		if review.TotalScore.Int() >
			best.TotalScore.Int() ||
			(review.TotalScore.Int() ==
				best.TotalScore.Int() &&
				review.Round > best.Round) {
			best = review
		}
	}

	return best, true
}

func orderedReviews(
	reviews []domain.PosterReviewRecord,
) []domain.PosterReviewRecord {
	ordered := append(
		[]domain.PosterReviewRecord(nil),
		reviews...,
	)

	sort.Slice(
		ordered,
		func(left int, right int) bool {
			return ordered[left].Round <
				ordered[right].Round
		},
	)

	return ordered
}
