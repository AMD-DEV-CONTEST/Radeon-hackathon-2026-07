package ai

import (
	"testing"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

// 词表只在提示词里收口是不够的。审查那边的 issue.Code 就是只收了提示词一侧，
// 服务端不校验，结果线上 94 条 issue 里 53 条落不到任何处理分支。这一组测试
// 盯的是服务端这一侧。
func TestNormalizeInspectionFoldsCasingAndSeparators(t *testing.T) {
	t.Parallel()

	cases := []struct {
		name    string
		in      domain.VisualInspection
		texture string
		style   string
		family  string
	}{
		{
			name: "already canonical",
			in: domain.VisualInspection{
				Texture: "film_grain",
				Style:   "vintage_print",
				Family:  "expressive_serif",
			},
			texture: "film_grain",
			style:   "vintage_print",
			family:  "expressive_serif",
		},
		{
			name: "hyphens and capitals",
			in: domain.VisualInspection{
				Texture: "Hand-Drawn-Grain",
				Style:   "Modern-Minimal",
				Family:  "Geometric-Sans",
			},
			texture: "hand_drawn_grain",
			style:   "modern_minimal",
			family:  "geometric_sans",
		},
		{
			name: "spaces and padding",
			in: domain.VisualInspection{
				Texture: "  halftone print ",
				Style:   " documentary photo ",
				Family:  " display slab ",
			},
			texture: "halftone_print",
			style:   "documentary_photo",
			family:  "display_slab",
		},
		{
			// 认不出来必须变空串，不能就近猜一个。前端拿到空串知道"模型没给
			// 判断"，拿到猜的值会当成事实去选字体。
			name: "invented values collapse to empty",
			in: domain.VisualInspection{
				Texture: "oil_impasto_swirl",
				Style:   "vaporwave_baroque",
				Family:  "comic_bubble",
			},
			texture: "",
			style:   "",
			family:  "",
		},
	}

	for _, item := range cases {
		t.Run(
			item.name,
			func(t *testing.T) {
				t.Parallel()

				result := item.in

				NormalizeInspection(&result)

				if result.Texture != item.texture {
					t.Errorf(
						"texture = %q, want %q",
						result.Texture,
						item.texture,
					)
				}

				if result.Style != item.style {
					t.Errorf(
						"style = %q, want %q",
						result.Style,
						item.style,
					)
				}

				if result.Family != item.family {
					t.Errorf(
						"family = %q, want %q",
						result.Family,
						item.family,
					)
				}
			},
		)
	}
}

// 模型列出了具体的伪文字，却把布尔位留成 false。以内容为准 —— 否则一张明确
// 带字的图会被放行。
func TestNormalizeInspectionTrustsListedTextOverTheFlag(t *testing.T) {
	t.Parallel()

	result := domain.VisualInspection{
		HasText: false,
		Text: []string{
			"AUGSST",
			"  ",
			"FESTVAL",
		},
	}

	NormalizeInspection(&result)

	if !result.HasText {
		t.Fatal(
			"listed pseudo-text must force hasGeneratedText to true",
		)
	}

	if len(result.Text) != 2 {
		t.Fatalf(
			"blank entries should be dropped, got %v",
			result.Text,
		)
	}
}

// 反过来不成立：说了有字但转录不出来是合理的（一团糊掉的笔画本来就认不出），
// 那种情况必须保留 true。
func TestNormalizeInspectionKeepsFlagWithoutTranscription(t *testing.T) {
	t.Parallel()

	result := domain.VisualInspection{
		HasText: true,
		Text:    nil,
	}

	NormalizeInspection(&result)

	if !result.HasText {
		t.Fatal(
			"an untranscribable smear is still pseudo-text",
		)
	}
}
