package ai

import (
	"testing"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func TestScoreNormalizesTenPointScale(
	t *testing.T,
) {
	var result domain.ReviewResult

	raw := `{
		"totalScore": 7.5,
		"scores": {
			"requirementAlignment": 8,
			"composition": 7,
			"typography": 6,
			"readability": 7,
			"visualQuality": 8,
			"brandConsistency": 7
		},
		"hardFailures": [],
		"issues": [],
		"decision": "RECOMPOSE",
		"nextInstruction": {
			"promptAdditions": [],
			"negativePromptAdditions": [],
			"composerTemplate": "cinematic_center"
		}
	}`

	if err := DecodeJSONObject(
		raw,
		&result,
	); err != nil {
		t.Fatalf(
			"DecodeJSONObject error: %v",
			err,
		)
	}

	if result.TotalScore.Int() != 75 {
		t.Fatalf(
			"expected 75, got %d",
			result.TotalScore.Int(),
		)
	}
}

func TestGeneratedTextForcesRegenerate(
	t *testing.T,
) {
	result := domain.ReviewResult{
		TotalScore: domain.Score(76),
		Decision:   domain.ReviewDecisionRecompose,
		Issues: []domain.ReviewIssue{
			{
				Code:        "GENERATED_GIBBERISH_TEXT",
				Description: "主视觉出现无意义文字",
			},
		},
	}

	if err := NormalizeReview(
		&result,
	); err != nil {
		t.Fatalf(
			"NormalizeReview error: %v",
			err,
		)
	}

	if result.Decision !=
		domain.ReviewDecisionRegenerate {
		t.Fatalf(
			"expected REGENERATE, got %s",
			result.Decision,
		)
	}
}

func TestDecodeJSONObjectFromCodeFence(
	t *testing.T,
) {
	raw := "```json\n{\"reply\":\"ok\"}\n```"

	var value struct {
		Reply string `json:"reply"`
	}

	if err := DecodeJSONObject(
		raw,
		&value,
	); err != nil {
		t.Fatalf(
			"DecodeJSONObject error: %v",
			err,
		)
	}

	if value.Reply != "ok" {
		t.Fatalf(
			"unexpected reply %q",
			value.Reply,
		)
	}
}
