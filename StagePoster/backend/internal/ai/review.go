package ai

import (
	"fmt"
	"strings"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func NormalizeReview(
	result *domain.ReviewResult,
) error {
	if result == nil {
		return fmt.Errorf("review result is nil")
	}

	if !result.Decision.Valid() {
		return fmt.Errorf(
			"invalid review decision %q",
			result.Decision,
		)
	}

	if len(result.Issues) > 10 {
		result.Issues = result.Issues[:10]
	}

	hasGenerationFailure := false
	hasCompositionFailure := false

	for index := range result.HardFailures {
		failure := &result.HardFailures[index]

		failure.Code = strings.ToUpper(
			strings.TrimSpace(failure.Code),
		)

		failure.Description = strings.TrimSpace(
			failure.Description,
		)

		if indicatesGenerationFailure(
			failure.Code + " " + failure.Description,
		) {
			hasGenerationFailure = true
		}
	}

	for index := range result.Issues {
		issue := &result.Issues[index]

		issue.Code = strings.ToUpper(
			strings.TrimSpace(issue.Code),
		)

		issue.Severity = normalizeSeverity(
			issue.Severity,
		)

		issue.Layer = normalizeLayer(issue.Layer)

		issue.Description = strings.TrimSpace(
			issue.Description,
		)

		issue.Suggestion = strings.TrimSpace(
			issue.Suggestion,
		)

		// layer 是模型自己声明的归属，优先于关键词。关键词只在 layer 缺失或
		// 无法识别时兜底 —— 否则一条 composition 问题只要描述里带个"水印"
		// 就会被误判成需要重新生成整张图。
		switch issue.Layer {
		case domain.ReviewIssueLayerGeneration:
			hasGenerationFailure = true

		case domain.ReviewIssueLayerComposition:
			hasCompositionFailure = true

		default:
			combined := issue.Code +
				" " +
				issue.Description

			if indicatesGenerationFailure(combined) {
				hasGenerationFailure = true
			}

			if indicatesCompositionFailure(combined) {
				hasCompositionFailure = true
			}
		}
	}

	switch {
	case hasGenerationFailure:
		result.Decision =
			domain.ReviewDecisionRegenerate

	case len(result.HardFailures) > 0 &&
		result.Decision ==
			domain.ReviewDecisionAccept:
		result.Decision =
			domain.ReviewDecisionRegenerate

	// 视觉质量塌了但排版分正常：瑕疵在像素里，重排版是白费。模型常在这种情况
	// 下仍然给 RECOMPOSE，重排若干轮都救不回来，最后撞上轮数上限，返回
	// completed_with_warnings。
	case pixelDefectDominates(result):
		result.Decision =
			domain.ReviewDecisionRegenerate

	case result.TotalScore.Int() >=
		domain.ReviewAcceptScore &&
		len(result.HardFailures) == 0 &&
		!hasCompositionFailure:
		result.Decision =
			domain.ReviewDecisionAccept

	case result.Decision ==
		domain.ReviewDecisionAccept:
		result.Decision =
			domain.ReviewDecisionRecompose
	}

	return nil
}

// pixelDefectDominates 判断"瑕疵烤进图里"：视觉质量明显偏低，而排版类分项
// 还站得住。只看 visualQuality 会把纯排版问题也拖去重新生成，所以要求排版
// 确实比视觉质量好一截。
func pixelDefectDominates(
	result *domain.ReviewResult,
) bool {
	visual := result.Scores.VisualQuality.Int()

	// 0 通常表示模型没给这一项，不能当成"极差"。
	if visual <= 0 ||
		visual >= domain.ReviewPixelDefectScore {
		return false
	}

	layout := minInt(
		result.Scores.Composition.Int(),
		minInt(
			result.Scores.Typography.Int(),
			result.Scores.Readability.Int(),
		),
	)

	if layout <= 0 {
		// 排版分缺失时只能靠 visualQuality 单独判断。
		return true
	}

	return layout >= visual+15
}

func minInt(a int, b int) int {
	if a < b {
		return a
	}

	return b
}

// normalizeLayer 把模型给的 layer 折叠到已知取值。识别不了的返回空串，
// 交给关键词兜底，而不是硬塞进某一类。
func normalizeLayer(
	value string,
) string {
	value = strings.ToLower(
		strings.TrimSpace(value),
	)

	switch value {
	case "generation",
		"generated",
		"keyvisual",
		"key_visual",
		"image",
		"pixels",
		"生成",
		"主视觉":
		return domain.ReviewIssueLayerGeneration

	case "composition",
		"layout",
		"typography",
		"text",
		"composer",
		"排版",
		"版式":
		return domain.ReviewIssueLayerComposition

	case "brief",
		"direction",
		"需求":
		return domain.ReviewIssueLayerBrief

	default:
		return ""
	}
}

func normalizeSeverity(
	value string,
) string {
	switch strings.ToLower(
		strings.TrimSpace(value),
	) {
	case "high":
		return "high"

	case "low":
		return "low"

	default:
		return "medium"
	}
}

func indicatesGenerationFailure(
	value string,
) bool {
	value = strings.ToLower(value)

	keywords := []string{
		"generated_gibberish_text",
		"gibberish",
		"malformed_text",
		"unwanted_text",
		"unwanted_logo",
		"watermark",
		"wrong_subject",
		"severe_artifact",
		"artifact",
		"distorted",
		"deformed",
		"blurry",
		"smudge",
		"flat white",
		"white panel",
		"white block",
		"乱码",
		"无意义文字",
		"伪文字",
		"错误文字",
		"生成文字",
		"水印",
		"畸形文字",
		"主体错误",
		"伪影",
		"扭曲",
		"模糊",
		"纯白色块",
		"白色色块",
		"纯白面板",
	}

	for _, keyword := range keywords {
		if strings.Contains(value, keyword) {
			return true
		}
	}

	return false
}

func indicatesCompositionFailure(
	value string,
) bool {
	value = strings.ToLower(value)

	keywords := []string{
		"title_collision",
		"layout",
		"typography",
		"readability",
		"information_panel",
		"spacing",
		"hierarchy",
		"contrast",
		"标题重叠",
		"排版",
		"字号",
		"可读性",
		"信息栏",
		"层级",
		"间距",
	}

	for _, keyword := range keywords {
		if strings.Contains(value, keyword) {
			return true
		}
	}

	return false
}
