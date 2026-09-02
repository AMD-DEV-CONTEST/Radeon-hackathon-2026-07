package assistant

import (
	"testing"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func TestBestReviewPrefersLatestRoundOnTie(
	t *testing.T,
) {
	t.Parallel()

	best, found := bestReview(
		[]domain.PosterReviewRecord{
			{
				Round:      1,
				TotalScore: domain.Score(88),
			},
			{
				Round:      2,
				TotalScore: domain.Score(88),
			},
		},
	)

	if !found {
		t.Fatal("best review not found")
	}

	if best.Round != 2 {
		t.Fatalf(
			"best round = %d, want 2",
			best.Round,
		)
	}
}

func TestBuildReviewSummaryWarning(
	t *testing.T,
) {
	t.Parallel()

	summary := buildReviewSummary(
		[]domain.PosterReviewRecord{
			{
				Round:      1,
				TotalScore: domain.Score(88),
				Decision:   domain.ReviewDecisionRecompose,
			},
			{
				Round:      2,
				TotalScore: domain.Score(88),
				Decision:   domain.ReviewDecisionRecompose,
			},
		},
		domain.AISessionStatusCompletedWithWarnings,
	)

	if summary == nil {
		t.Fatal("summary is nil")
	}

	if !summary.Finalized {
		t.Fatal("summary is not finalized")
	}

	if summary.Accepted {
		t.Fatal("summary unexpectedly accepted")
	}

	if summary.BestRound != 2 {
		t.Fatalf(
			"best round = %d, want 2",
			summary.BestRound,
		)
	}

	if summary.Warning == "" {
		t.Fatal("warning is empty")
	}
}
