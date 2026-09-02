package ai

import (
	"strings"
	"testing"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func normalized(
	t *testing.T,
	result domain.ReviewResult,
) domain.ReviewResult {
	t.Helper()

	if err := NormalizeReview(&result); err != nil {
		t.Fatalf("normalize review: %v", err)
	}

	return result
}

// 模型识别出了问题却给 RECOMPOSE，而瑕疵已经烤进像素里 —— 重排版救不了，
// 重排若干轮后撞上轮数上限，返回 completed_with_warnings。
// visualQuality 明显低于排版分时必须升级成 REGENERATE。
func TestLowVisualQualityEscalatesToRegenerate(
	t *testing.T,
) {
	t.Parallel()

	result := normalized(t, domain.ReviewResult{
		TotalScore: 75,
		Scores: domain.ReviewScores{
			Composition:   88,
			Typography:    85,
			Readability:   84,
			VisualQuality: 42,
		},
		Issues: []domain.ReviewIssue{
			{
				Code:        "KEY_VISUAL_QUALITY",
				Description: "主视觉下部有一块低细节区域",
			},
		},
		Decision: domain.ReviewDecisionRecompose,
	})

	if result.Decision !=
		domain.ReviewDecisionRegenerate {
		t.Fatalf(
			"expected REGENERATE, got %s",
			result.Decision,
		)
	}
}

// 反面：纯排版问题不能被拖去重新生成，那样白烧一次 GPU。
func TestLayoutOnlyStaysRecompose(
	t *testing.T,
) {
	t.Parallel()

	result := normalized(t, domain.ReviewResult{
		TotalScore: 70,
		Scores: domain.ReviewScores{
			Composition:   55,
			Typography:    52,
			Readability:   50,
			VisualQuality: 86,
		},
		Issues: []domain.ReviewIssue{
			{
				Code:        "TITLE_COLLISION",
				Layer:       domain.ReviewIssueLayerComposition,
				Description: "标题与主体重叠",
			},
		},
		Decision: domain.ReviewDecisionRecompose,
	})

	if result.Decision !=
		domain.ReviewDecisionRecompose {
		t.Fatalf(
			"expected RECOMPOSE, got %s",
			result.Decision,
		)
	}
}

// layer 以前解析完就扔了，路由只看自由文本。于是一条 composition 层的问题
// 只要描述里出现"水印"就会被误判成需要重新生成整张图。
func TestLayerOutranksKeywordMatch(
	t *testing.T,
) {
	t.Parallel()

	result := normalized(t, domain.ReviewResult{
		TotalScore: 79,
		Scores: domain.ReviewScores{
			Composition:   70,
			Typography:    72,
			Readability:   71,
			VisualQuality: 85,
		},
		Issues: []domain.ReviewIssue{
			{
				Code:  "INFORMATION_PANEL",
				Layer: domain.ReviewIssueLayerComposition,
				// 描述里提到水印，但归属是排版层：
				// 赞助商水印区的位置需要下移，不是图里有水印。
				Description: "赞助商水印区位置偏高，需要下移",
			},
		},
		Decision: domain.ReviewDecisionRecompose,
	})

	if result.Decision !=
		domain.ReviewDecisionRecompose {
		t.Fatalf(
			"composition layer misrouted to %s",
			result.Decision,
		)
	}
}

// layer 声明为 generation 时，即使描述里没有任何关键词也要重新生成。
func TestGenerationLayerForcesRegenerate(
	t *testing.T,
) {
	t.Parallel()

	result := normalized(t, domain.ReviewResult{
		TotalScore: 90,
		Scores: domain.ReviewScores{
			Composition:   92,
			Typography:    91,
			Readability:   90,
			VisualQuality: 88,
		},
		Issues: []domain.ReviewIssue{
			{
				Code:        "SUBJECT_MISMATCH",
				Layer:       domain.ReviewIssueLayerGeneration,
				Description: "画面主体与需求不符",
			},
		},
		Decision: domain.ReviewDecisionAccept,
	})

	if result.Decision !=
		domain.ReviewDecisionRegenerate {
		t.Fatalf(
			"generation layer not escalated: %s",
			result.Decision,
		)
	}
}

// layer 缺失时回落到关键词匹配，原有行为不能退化。
func TestKeywordFallbackWithoutLayer(
	t *testing.T,
) {
	t.Parallel()

	result := normalized(t, domain.ReviewResult{
		TotalScore: 88,
		Scores: domain.ReviewScores{
			Composition:   90,
			Typography:    90,
			Readability:   90,
			VisualQuality: 90,
		},
		Issues: []domain.ReviewIssue{
			{
				Code:        "GENERATED_GIBBERISH_TEXT",
				Description: "画面里有乱码文字",
			},
		},
		Decision: domain.ReviewDecisionAccept,
	})

	if result.Decision !=
		domain.ReviewDecisionRegenerate {
		t.Fatalf(
			"keyword fallback broken: %s",
			result.Decision,
		)
	}
}

// 干净的高分结果仍然要能通过。
func TestCleanResultAccepted(
	t *testing.T,
) {
	t.Parallel()

	result := normalized(t, domain.ReviewResult{
		TotalScore: domain.ReviewAcceptScore,
		Scores: domain.ReviewScores{
			Composition:   90,
			Typography:    88,
			Readability:   87,
			VisualQuality: 86,
		},
		Decision: domain.ReviewDecisionRecompose,
	})

	if result.Decision !=
		domain.ReviewDecisionAccept {
		t.Fatalf(
			"clean result not accepted: %s",
			result.Decision,
		)
	}
}

// visualQuality 缺失（0）不能被当成"极差"，否则每张图都会被拖去重新生成。
func TestMissingVisualQualityDoesNotRegenerate(
	t *testing.T,
) {
	t.Parallel()

	result := normalized(t, domain.ReviewResult{
		TotalScore: 70,
		Scores: domain.ReviewScores{
			Composition: 70,
			Typography:  70,
			Readability: 70,
		},
		Decision: domain.ReviewDecisionRecompose,
	})

	if result.Decision ==
		domain.ReviewDecisionRegenerate {
		t.Fatal(
			"absent visualQuality treated as pixel defect",
		)
	}
}

// 提示词里的阈值必须和服务端裁决用的是同一个数。
func TestPromptQuotesAcceptThreshold(
	t *testing.T,
) {
	t.Parallel()

	if !strings.Contains(
		reviewSystemPrompt,
		reviewAcceptScoreText,
	) {
		t.Fatalf(
			"review prompt does not mention threshold %s",
			reviewAcceptScoreText,
		)
	}

	if reviewAcceptScoreText != "82" {
		t.Fatalf(
			"accept threshold drifted: %s",
			reviewAcceptScoreText,
		)
	}
}
