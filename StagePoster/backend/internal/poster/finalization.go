package poster

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

var ErrReviewSnapshotNotFound = errors.New(
	"review snapshot is not available",
)

func (s *Service) RecomposeFromReview(
	ctx context.Context,
	posterID string,
	result domain.ReviewResult,
	round int,
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

	if posterRecord.Status !=
		domain.PosterStatusSucceeded {
		return fmt.Errorf(
			"cannot recompose poster while status is %s",
			posterRecord.Status,
		)
	}

	if err := s.repository.UpdatePosterStatus(
		ctx,
		posterID,
		domain.PosterStatusComposing,
		"",
	); err != nil {
		return err
	}

	posterRecord.Status =
		domain.PosterStatusComposing

	if err := s.composePoster(
		ctx,
		posterRecord,
		reviewAdjustments(result, round),
		"",
	); err != nil {
		return err
	}

	return s.requireSuccessfulComposition(
		ctx,
		posterID,
	)
}

func (s *Service) RegenerateFromReview(
	ctx context.Context,
	posterID string,
	result domain.ReviewResult,
	round int,
) error {
	posterRecord, err := s.repository.GetPoster(
		ctx,
		posterID,
	)
	if err != nil {
		return err
	}

	if posterRecord.Status !=
		domain.PosterStatusSucceeded {
		return fmt.Errorf(
			"cannot regenerate poster while status is %s",
			posterRecord.Status,
		)
	}

	candidate, err :=
		s.repository.GetSelectedCandidate(
			ctx,
			posterID,
		)
	if err != nil {
		return err
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

	prompt := joinPromptFragments(
		candidate.CompiledPrompt,
		result.NextInstruction.PromptAdditions,
	)

	negativePrompt := joinPromptFragments(
		"text, letters, words, typography, caption, logo, watermark, signage, gibberish",
		result.NextInstruction.NegativePromptAdditions,
	)

	nextAttempt := candidate.Attempt + 1
	nextSeed := candidate.Seed +
		int64(nextAttempt*1000003)

	generation, err := s.core.Generate(
		ctx,
		applyReferenceControl(
			domain.GenerateRequest{
				Prompt:         prompt,
				NegativePrompt: negativePrompt,
				Seed:           &nextSeed,
			},
			visualBriefFrom(posterRecord),
		),
	)
	if err != nil {
		return fmt.Errorf(
			"submit regenerated key visual: %w",
			err,
		)
	}

	output, err := s.waitForGeneratedOutput(
		ctx,
		generation.JobID,
	)
	if err != nil {
		return err
	}

	if err := s.evaluator.Evaluate(
		output,
		goal,
	); err != nil {
		return fmt.Errorf(
			"evaluate regenerated key visual: %w",
			err,
		)
	}

	s.reconcileMu.Lock()
	defer s.reconcileMu.Unlock()

	if err := s.repository.AdoptCandidateJob(
		ctx,
		candidate.ID,
		generation.JobID,
		nextSeed,
		nextAttempt,
	); err != nil {
		return fmt.Errorf(
			"adopt regenerated candidate job: %w",
			err,
		)
	}

	if err := s.repository.UpdatePosterStatus(
		ctx,
		posterID,
		domain.PosterStatusComposing,
		"",
	); err != nil {
		return err
	}

	posterRecord.Status =
		domain.PosterStatusComposing

	if err := s.composePoster(
		ctx,
		posterRecord,
		reviewAdjustments(result, round),
		output.StoragePath,
	); err != nil {
		return err
	}

	return s.requireSuccessfulComposition(
		ctx,
		posterID,
	)
}

func (s *Service) waitForGeneratedOutput(
	ctx context.Context,
	jobID string,
) (domain.Output, error) {
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	for {
		status, err := s.core.Status(
			ctx,
			jobID,
		)
		if err != nil {
			return domain.Output{},
				fmt.Errorf(
					"read regenerated job status: %w",
					err,
				)
		}

		switch status.Status {
		case domain.JobStatusSucceeded:
			output, outputErr :=
				s.repository.GetOutput(
					ctx,
					jobID,
					"poster",
				)
			if outputErr != nil {
				return domain.Output{},
					fmt.Errorf(
						"read regenerated output: %w",
						outputErr,
					)
			}

			return output, nil

		case domain.JobStatusFailed,
			domain.JobStatusCanceled:

			return domain.Output{},
				fmt.Errorf(
					"regenerated key visual failed: %s",
					status.Error,
				)
		}

		select {
		case <-ctx.Done():
			return domain.Output{}, ctx.Err()

		case <-ticker.C:
		}
	}
}

func (s *Service) requireSuccessfulComposition(
	ctx context.Context,
	posterID string,
) error {
	posterRecord, err := s.repository.GetPoster(
		ctx,
		posterID,
	)
	if err != nil {
		return err
	}

	if posterRecord.Status !=
		domain.PosterStatusSucceeded {
		return fmt.Errorf(
			"poster composition did not succeed: %s",
			posterRecord.ErrorMessage,
		)
	}

	return nil
}

func (s *Service) SnapshotReviewRound(
	ctx context.Context,
	posterID string,
	round int,
) error {
	if round <= 0 {
		return fmt.Errorf(
			"invalid review round %d",
			round,
		)
	}

	for _, kind := range []string{
		domain.PosterOutputKindFinal,
		domain.PosterOutputKindThumbnail,
	} {
		output, err := s.repository.GetPosterOutput(
			ctx,
			posterID,
			kind,
		)
		if err != nil {
			return err
		}

		target := reviewSnapshotPath(
			output.StoragePath,
			round,
			kind,
		)

		if _, err := os.Stat(target); err == nil {
			continue
		} else if !errors.Is(err, os.ErrNotExist) {
			return err
		}

		if err := copyFileAtomic(
			output.StoragePath,
			target,
		); err != nil {
			return fmt.Errorf(
				"snapshot %s for review round %d: %w",
				kind,
				round,
				err,
			)
		}
	}

	return nil
}

func (s *Service) RestoreReviewRound(
	ctx context.Context,
	posterID string,
	round int,
) error {
	for _, kind := range []string{
		domain.PosterOutputKindFinal,
		domain.PosterOutputKindThumbnail,
	} {
		output, err := s.repository.GetPosterOutput(
			ctx,
			posterID,
			kind,
		)
		if err != nil {
			return err
		}

		source := reviewSnapshotPath(
			output.StoragePath,
			round,
			kind,
		)

		if _, err := os.Stat(source); err != nil {
			if errors.Is(err, os.ErrNotExist) {
				return fmt.Errorf(
					"%w: round %d %s",
					ErrReviewSnapshotNotFound,
					round,
					kind,
				)
			}

			return err
		}

		if err := copyFileAtomic(
			source,
			output.StoragePath,
		); err != nil {
			return fmt.Errorf(
				"restore %s from review round %d: %w",
				kind,
				round,
				err,
			)
		}
	}

	return s.repository.CompletePoster(
		ctx,
		posterID,
	)
}

func (s *Service) KeepExistingResult(
	ctx context.Context,
	posterID string,
) error {
	for _, kind := range []string{
		domain.PosterOutputKindFinal,
		domain.PosterOutputKindThumbnail,
	} {
		output, err := s.repository.GetPosterOutput(
			ctx,
			posterID,
			kind,
		)
		if err != nil {
			return err
		}

		if _, err := os.Stat(
			output.StoragePath,
		); err != nil {
			return err
		}
	}

	return s.repository.CompletePoster(
		ctx,
		posterID,
	)
}

// 版式微调的单步步长。步长乘以轮次，所以第 2 轮的调整幅度必然大于第 1 轮。
const (
	reviewTitleStep = 0.02
	reviewPanelStep = 0.02
)

// reviewAdjustments 把审查结论翻译成版式调整。
//
// scale 是轮次：第 1 轮传 1，第 2 轮传 2。scale=0 表示"原始合成时生效的值"，
// 用来判断新算出的调整是否真的改变了什么。
//
// 原先这里对 TITLE 类问题直接 maxFloat(..., 0.055)、对 INFORMATION_PANEL 直接
// maxFloat(..., 0.81)。问题在于这两个数**就是 cinematic_center 模板的默认值**
// （domain.NormalizeCompositionAdjustments），所以对该模板的海报，"调整"之后
// 重排产出的是同一张图，VLM 自然给同一个分。线上 15 组配对里 8 组 delta 恰好
// 为 0，RECOMPOSE 的平均增益是 -0.7，而 REGENERATE 是 +4.8。
//
// 现在改成：先解析出模板的生效基线，再在基线上按轮次叠加步进。
func reviewAdjustmentsAtScale(
	result domain.ReviewResult,
	scale float64,
) domain.CompositionAdjustments {

	template := strings.TrimSpace(
		result.NextInstruction.ComposerTemplate,
	)

	// 基线 = 该模板实际生效的值，不是零值。
	adjustments := domain.NormalizeCompositionAdjustments(
		domain.CompositionAdjustments{
			Template: template,
		},
	)

	adjustments.Template = template

	// 每个类别最多计一次，避免同类问题重复叠加把版式推到边界。
	var (
		nudgeTitle bool
		nudgePanel bool
		darkPanel  bool
	)

	for _, issue := range result.Issues {
		code := strings.ToUpper(
			strings.TrimSpace(issue.Code),
		)

		switch {
		case strings.Contains(
			code,
			"TITLE",
		):
			nudgeTitle = true

		case strings.Contains(
			code,
			"INFORMATION_PANEL_CONTRAST",
		):
			darkPanel = true
			nudgePanel = true

		case strings.Contains(
			code,
			"INFORMATION_PANEL",
		):
			nudgePanel = true

		case strings.Contains(code, "SPACING"),
			strings.Contains(code, "HIERARCHY"),
			strings.Contains(code, "LAYOUT"):

			nudgeTitle = true
			nudgePanel = true
		}
	}

	if nudgeTitle {
		adjustments.TitleOffsetRatio +=
			reviewTitleStep * scale
	}

	if nudgePanel {
		adjustments.PanelTopRatio +=
			reviewPanelStep * scale
	}

	if darkPanel {
		adjustments.PanelTheme = "dark"
	}

	// 再归一化一次，把叠加后的值夹回合法区间。
	return domain.NormalizeCompositionAdjustments(adjustments)
}

func reviewAdjustments(
	result domain.ReviewResult,
	round int,
) domain.CompositionAdjustments {
	return reviewAdjustmentsAtScale(
		result,
		float64(round),
	)
}

// ReviewAdjustmentsAreNoOp 判断这一轮重排是否必然产出与上一轮相同的图。
//
// 两种情况会为真：
//   - 没有任何 issue.Code 命中词表（线上 86 条 issue 里 47 条如此），
//     于是调整等于模板基线，也就是已经生效的那份；
//   - 递增之后被夹回了同一个边界值，再排一次也没有意义。
//
// 命中任一情况就不该烧掉一轮去产出同一张图。
func ReviewAdjustmentsAreNoOp(
	result domain.ReviewResult,
	round int,
) bool {
	return reviewAdjustments(result, round) ==
		reviewAdjustmentsAtScale(
			result,
			float64(round-1),
		)
}

func joinPromptFragments(
	base string,
	additions []string,
) string {
	parts := make([]string, 0, len(additions)+1)

	if value := strings.TrimSpace(base); value != "" {
		parts = append(parts, value)
	}

	for _, addition := range additions {
		if value := strings.TrimSpace(addition); value != "" {
			parts = append(parts, value)
		}
	}

	return strings.Join(parts, ", ")
}

func reviewSnapshotPath(
	outputPath string,
	round int,
	kind string,
) string {
	extension := filepath.Ext(outputPath)
	if extension == "" {
		extension = ".png"
	}

	return filepath.Join(
		filepath.Dir(outputPath),
		fmt.Sprintf(
			"review-round-%d-%s%s",
			round,
			kind,
			extension,
		),
	)
}

func copyFileAtomic(
	source string,
	target string,
) error {
	input, err := os.Open(source)
	if err != nil {
		return err
	}
	defer input.Close()

	if err := os.MkdirAll(
		filepath.Dir(target),
		0o755,
	); err != nil {
		return err
	}

	temporary, err := os.CreateTemp(
		filepath.Dir(target),
		".stageposter-copy-*",
	)
	if err != nil {
		return err
	}

	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)

	if _, err := io.Copy(
		temporary,
		input,
	); err != nil {
		temporary.Close()
		return err
	}

	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return err
	}

	if err := temporary.Close(); err != nil {
		return err
	}

	return os.Rename(
		temporaryPath,
		target,
	)
}

func maxFloat(
	left float64,
	right float64,
) float64 {
	if left > right {
		return left
	}

	return right
}
