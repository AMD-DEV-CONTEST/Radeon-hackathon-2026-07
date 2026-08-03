package poster

import (
	"testing"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func recomposeResult(
	codes ...string,
) domain.ReviewResult {

	issues := make(
		[]domain.ReviewIssue,
		0,
		len(codes),
	)

	for _, code := range codes {
		issues = append(
			issues,
			domain.ReviewIssue{
				Code: code,
			},
		)
	}

	return domain.ReviewResult{
		Issues: issues,
		NextInstruction: domain.ReviewNextInstruction{
			ComposerTemplate: "cinematic_center",
		},
	}
}

func TestReviewAdjustments(t *testing.T) {
	t.Parallel()

	adjustments := reviewAdjustments(
		recomposeResult(
			"TITLE_COLLISION",
			"INFORMATION_PANEL_CONTRAST",
		),
		1,
	)

	if adjustments.Template != "cinematic_center" {
		t.Fatalf(
			"template = %q",
			adjustments.Template,
		)
	}

	if adjustments.PanelTheme != "dark" {
		t.Fatalf(
			"panel theme = %q",
			adjustments.PanelTheme,
		)
	}
}

// TestReviewAdjustmentsDifferFromTemplateDefaults 是这一组里唯一真正重要的断言。
//
// 旧测试只断言 TitleOffsetRatio >= 0.05、PanelTopRatio >= 0.80，而
// cinematic_center 的默认值恰好是 0.055 和 0.81 —— 于是即便 reviewAdjustments
// 什么都没做（返回模板默认值），测试也照样通过。这就是这个缺陷能活到线上、
// 并在 15 组配对里制造 8 组 delta=0 的原因。
//
// 判据必须是"和基线不同"，而不是"大于某个恰好等于基线的常数"。
func TestReviewAdjustmentsDifferFromTemplateDefaults(t *testing.T) {
	t.Parallel()

	baseline := domain.NormalizeCompositionAdjustments(
		domain.CompositionAdjustments{
			Template: "cinematic_center",
		},
	)

	adjustments := reviewAdjustments(
		recomposeResult(
			"TITLE_COLLISION",
			"INFORMATION_PANEL_CONTRAST",
		),
		1,
	)

	if adjustments.TitleOffsetRatio ==
		baseline.TitleOffsetRatio {
		t.Fatalf(
			"title offset unchanged from template default %f — recompose would produce an identical image",
			baseline.TitleOffsetRatio,
		)
	}

	if adjustments.PanelTopRatio ==
		baseline.PanelTopRatio {
		t.Fatalf(
			"panel top unchanged from template default %f — recompose would produce an identical image",
			baseline.PanelTopRatio,
		)
	}
}

// 第 2 轮必须和第 1 轮不同，否则第二次重排是纯浪费。
func TestReviewAdjustmentsEscalateByRound(t *testing.T) {
	t.Parallel()

	result := recomposeResult("TITLE_COLLISION")

	first := reviewAdjustments(result, 1)
	second := reviewAdjustments(result, 2)

	if first.TitleOffsetRatio >=
		second.TitleOffsetRatio {
		t.Fatalf(
			"round 2 did not escalate: round1=%f round2=%f",
			first.TitleOffsetRatio,
			second.TitleOffsetRatio,
		)
	}
}

func TestReviewAdjustmentsAreNoOpWhenNoCodeMatches(t *testing.T) {
	t.Parallel()

	// 线上 86 条 issue 里有 47 条是这种词表匹配不到的自造 code。
	// 它们让调整退化成模板基线，也就是已经生效的那份。
	result := recomposeResult(
		"VENUE_TEXT_MISSING",
		"COLOR_PALETTE_DRIFT",
	)

	if !ReviewAdjustmentsAreNoOp(result, 1) {
		t.Fatal(
			"expected a no-op: no issue code matches the adjustment vocabulary",
		)
	}
}

func TestReviewAdjustmentsAreNotNoOpWhenCodeMatches(t *testing.T) {
	t.Parallel()

	result := recomposeResult("TITLE_COLLISION")

	if ReviewAdjustmentsAreNoOp(result, 1) {
		t.Fatal(
			"TITLE_COLLISION should produce a real layout change",
		)
	}
}

// 顶到夹取边界之后，再递增也换不到新图，应当判为 no-op。
func TestReviewAdjustmentsAreNoOpAtClamp(t *testing.T) {
	t.Parallel()

	result := recomposeResult("TITLE_COLLISION")

	// 步长 0.02，上限 0.12，基线 0.055 —— 轮次足够大时必然夹到上限。
	const farRound = 50

	if !ReviewAdjustmentsAreNoOp(result, farRound) {
		t.Fatalf(
			"expected a no-op once clamped at %f",
			domain.CompositionTitleOffsetMax,
		)
	}
}
