package poster

import (
	"context"
	"errors"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
	"github.com/Ripped-sys/StagePoster/backend/internal/repository"
)

type ReviewMaterial struct {
	Poster    domain.PosterRecord     `json:"poster"`
	Output    domain.PosterOutput     `json:"output"`
	Candidate *domain.CandidateRecord `json:"candidate,omitempty"`
}

func (s *Service) ReviewMaterial(
	ctx context.Context,
	posterID string,
) (ReviewMaterial, error) {
	posterRecord, err := s.repository.GetPoster(
		ctx,
		posterID,
	)
	if err != nil {
		return ReviewMaterial{}, err
	}

	output, err := s.repository.GetPosterOutput(
		ctx,
		posterID,
		domain.PosterOutputKindFinal,
	)
	if errors.Is(err, repository.ErrNotFound) {
		return ReviewMaterial{}, ErrResultNotReady
	}

	if err != nil {
		return ReviewMaterial{}, err
	}

	material := ReviewMaterial{
		Poster: posterRecord,
		Output: output,
	}

	candidate, candidateErr :=
		s.repository.GetSelectedCandidate(
			ctx,
			posterID,
		)

	if candidateErr == nil {
		material.Candidate = &candidate
	} else if !errors.Is(
		candidateErr,
		repository.ErrNotFound,
	) {
		return ReviewMaterial{}, candidateErr
	}

	return material, nil
}

func (s *Service) NextReviewRound(
	ctx context.Context,
	posterID string,
) (int, error) {
	return s.repository.NextPosterReviewRound(
		ctx,
		posterID,
	)
}

func (s *Service) SaveReview(
	ctx context.Context,
	review domain.PosterReviewRecord,
) error {
	return s.repository.CreatePosterReview(
		ctx,
		review,
	)
}

// ListReviews 返回一页复审记录和该海报的复审总轮数。
// 总数是分页必需的：只有当前页行数的话，客户端没法知道还有没有下一页。
func (s *Service) ListReviews(
	ctx context.Context,
	posterID string,
	page domain.Page,
) ([]domain.PosterReviewRecord, int, error) {
	// 先确认 poster 存在，避免未知 poster 返回空数组。
	if _, err := s.repository.GetPoster(
		ctx,
		posterID,
	); err != nil {
		return nil, 0, err
	}

	reviews, err := s.repository.ListPosterReviews(
		ctx,
		posterID,
		page,
	)
	if err != nil {
		return nil, 0, err
	}

	total, err := s.repository.CountPosterReviews(
		ctx,
		posterID,
	)
	if err != nil {
		return nil, 0, err
	}

	return reviews, total, nil
}

// Metrics 返回一张海报的任务级成本汇总：复审轮数、累计 token、累计复审耗时，
// 以及包含 GPU 排队与图像生成的墙上时间。
func (s *Service) Metrics(
	ctx context.Context,
	posterID string,
) (domain.PosterMetrics, error) {
	posterRecord, err := s.repository.GetPoster(
		ctx,
		posterID,
	)
	if err != nil {
		return domain.PosterMetrics{}, err
	}

	metrics, err := s.repository.
		AggregatePosterReviewMetrics(ctx, posterID)
	if err != nil {
		return domain.PosterMetrics{}, err
	}

	metrics.WallClockSeconds = int(
		posterRecord.UpdatedAt.
			Sub(posterRecord.CreatedAt).
			Seconds(),
	)

	return metrics, nil
}
