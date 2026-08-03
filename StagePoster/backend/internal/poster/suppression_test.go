package poster

import (
	"strings"
	"testing"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

// 主视觉必须无字。这一组盯的是"负向提示词里到底有没有那些词"，而不是它拼出来
// 好不好看 —— 用户明确要求禁止文字、字母、数字、Logo、水印和票务信息。
func TestNegativePromptCoversEveryForbiddenCategory(t *testing.T) {
	t.Parallel()

	prompt := negativePromptWith()

	required := []string{
		// 文字本体
		"text",
		"letters",
		"numbers",
		"digits",
		"chinese characters",
		// 排版产物
		"typography",
		"logo",
		"wordmark",
		"watermark",
		// 票务信息
		"ticket",
		"price tag",
		"QR code",
		"barcode",
		// 留白面板
		"solid white panel",
	}

	lowered := strings.ToLower(prompt)

	for _, term := range required {
		if !strings.Contains(
			lowered,
			strings.ToLower(term),
		) {
			t.Errorf(
				"negative prompt is missing %q",
				term,
			)
		}
	}
}

func TestNegativePromptPutsCallerFragmentsFirst(t *testing.T) {
	t.Parallel()

	prompt := negativePromptWith(
		"avoid purple",
		"no neon",
	)

	if !strings.HasPrefix(
		prompt,
		"avoid purple, no neon, ",
	) {
		t.Fatalf(
			"caller fragments should lead: %q",
			prompt,
		)
	}
}

// 去重是大小写不敏感的，否则调用方传 "Text" 会和词表里的 "text" 各占一份。
func TestNegativePromptDeduplicatesCaseInsensitively(t *testing.T) {
	t.Parallel()

	prompt := negativePromptWith("TEXT", "text", "Text")

	count := 0

	for _, fragment := range strings.Split(prompt, ", ") {
		if strings.EqualFold(fragment, "text") {
			count++
		}
	}

	if count != 1 {
		t.Fatalf(
			"expected exactly one text fragment, got %d in %q",
			count,
			prompt,
		)
	}
}

func TestNegativePromptSkipsBlankFragments(t *testing.T) {
	t.Parallel()

	prompt := negativePromptWith("", "   ", "no neon")

	if strings.HasPrefix(prompt, ",") ||
		strings.Contains(prompt, ", ,") {
		t.Fatalf(
			"blank fragments leaked into the prompt: %q",
			prompt,
		)
	}

	if !strings.HasPrefix(prompt, "no neon, ") {
		t.Fatalf(
			"expected the only real fragment to lead: %q",
			prompt,
		)
	}
}

// 设计方案自带的负向提示词必须保留，同时被文字抑制词表兜住。
func TestDesignPlanNegativePromptKeepsPlanFragment(t *testing.T) {
	t.Parallel()

	prompt := buildDesignPlanNegativePrompt(
		domain.DesignPlan{
			NegativePrompt: "no pastel gradients",
		},
	)

	if !strings.HasPrefix(
		prompt,
		"no pastel gradients, ",
	) {
		t.Fatalf(
			"plan fragment should lead: %q",
			prompt,
		)
	}

	if !strings.Contains(prompt, "watermark") {
		t.Fatalf(
			"plan prompt lost the suppression vocabulary: %q",
			prompt,
		)
	}
}

// decodeAnalysis 决定候选响应里到底给不给 visualAnalysis。空串必须是错误，
// 否则前端会收到一份"没有主体、没有安全区、也没有伪文字"的零值分析 —— 三句
// 都不是事实。
func TestDecodeAnalysisRejectsEmptyAndInvalid(t *testing.T) {
	t.Parallel()

	if _, err := decodeAnalysis(""); err == nil {
		t.Fatal("empty analysis must be an error")
	}

	if _, err := decodeAnalysis(
		"{not json",
	); err == nil {
		t.Fatal("malformed analysis must be an error")
	}

	analysis, err := decodeAnalysis(
		`{"source":"pixels","palette":["#101010"]}`,
	)
	if err != nil {
		t.Fatal(err)
	}

	if analysis.Source != domain.VisualSourcePixels {
		t.Fatalf(
			"source = %q",
			analysis.Source,
		)
	}
}

// inspected 决定要不要再烧一次 GPU 去问同一张图。
func TestInspectedOnlyTrueAfterAVLMPass(t *testing.T) {
	t.Parallel()

	if inspected("") {
		t.Fatal("empty analysis has not been inspected")
	}

	if inspected(
		`{"source":"pixels"}`,
	) {
		t.Fatal(
			"pixel-only analysis has not been inspected",
		)
	}

	if !inspected(
		`{"source":"pixels+vlm"}`,
	) {
		t.Fatal(
			"a merged analysis should count as inspected",
		)
	}
}
