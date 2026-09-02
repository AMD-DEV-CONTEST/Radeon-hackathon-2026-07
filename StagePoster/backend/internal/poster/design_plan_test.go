package poster

import (
	"strings"
	"testing"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func testDesignPlan() domain.DesignPlan {
	return domain.DesignPlan{
		ID:             "chaos-clash-red",
		Name:           "Chaos Clash",
		Concept:        "a fractured monolith of stacked amplifiers",
		PositivePrompt: "dark industrial concert key visual",
		NegativePrompt: "blurry",
		Palette: []string{
			"ink black",
			"oxide red",
		},
		Composition: domain.DesignComposition{
			Subject:             "a fractured monolith of stacked amplifiers",
			Symmetry:            "central symmetry",
			TitleSafeZone:       "upper 18 percent",
			InformationSafeZone: "lower 22 percent",
		},
	}
}

// 三个候选必须在主体取景、镜头、构图、灯光上真正拉开差距，
// 否则用户拿到的是三张几乎相同的图。
func TestDesignPlanVariantsAreDistinct(
	t *testing.T,
) {
	t.Parallel()

	variants := buildDesignPlanVariants(
		testDesignPlan(),
	)

	if len(variants) != 3 {
		t.Fatalf(
			"expected 3 variants, got %d",
			len(variants),
		)
	}

	fields := map[string]func(designPlanVariant) string{
		"variantKey":  func(v designPlanVariant) string { return v.Spec.VariantKey },
		"motif":       func(v designPlanVariant) string { return v.Spec.Motif },
		"composition": func(v designPlanVariant) string { return v.Spec.Composition },
		"camera":      func(v designPlanVariant) string { return v.Spec.Camera },
		"lighting":    func(v designPlanVariant) string { return v.Spec.Lighting },
		"materials":   func(v designPlanVariant) string { return strings.Join(v.Spec.Materials, ",") },
		"addition":    func(v designPlanVariant) string { return v.PromptAddition },
	}

	for name, extract := range fields {
		seen := make(map[string]struct{}, len(variants))

		for _, variant := range variants {
			value := extract(variant)

			if strings.TrimSpace(value) == "" {
				t.Fatalf(
					"%s is empty for %s",
					name,
					variant.Spec.VariantKey,
				)
			}

			if _, exists := seen[value]; exists {
				t.Fatalf(
					"%s is shared across variants: %q",
					name,
					value,
				)
			}

			seen[value] = struct{}{}
		}
	}
}

// 每个候选的安全区约束是共享的排版契约，不能因为差异化被弄丢。
func TestDesignPlanVariantsKeepSafeZones(
	t *testing.T,
) {
	t.Parallel()

	for _, variant := range buildDesignPlanVariants(
		testDesignPlan(),
	) {
		for _, fragment := range []string{
			"upper 18 percent",
			"lower 22 percent",
		} {
			if !strings.Contains(
				variant.Spec.Composition,
				fragment,
			) {
				t.Fatalf(
					"%s lost safe zone %q: %s",
					variant.Spec.VariantKey,
					fragment,
					variant.Spec.Composition,
				)
			}
		}
	}
}

// 差异化信息只落库不进 prompt 等于没做——ComfyUI 只看得到 prompt。
func TestDesignPlanPromptCarriesVariantDetail(
	t *testing.T,
) {
	t.Parallel()

	plan := testDesignPlan()

	for _, variant := range buildDesignPlanVariants(plan) {
		prompt := buildDesignPlanPrompt(plan, variant)

		for label, fragment := range map[string]string{
			"positive prompt": plan.PositivePrompt,
			"prompt addition": variant.PromptAddition,
			"motif":           variant.Spec.Motif,
			"composition":     variant.Spec.Composition,
			"camera":          variant.Spec.Camera,
			"lighting":        variant.Spec.Lighting,
		} {
			if !strings.Contains(prompt, fragment) {
				t.Fatalf(
					"%s prompt is missing the %s: %s",
					variant.Spec.VariantKey,
					label,
					prompt,
				)
			}
		}
	}
}

// 标题安全区不能靠画白块实现。正向词里不许出现“空白/干净”的措辞，
// 负向词必须显式压制白色色块。
func TestDesignPlanPromptForbidsWhitePanels(
	t *testing.T,
) {
	t.Parallel()

	plan := testDesignPlan()
	variants := buildDesignPlanVariants(plan)

	for _, variant := range variants {
		prompt := strings.ToLower(
			buildDesignPlanPrompt(plan, variant),
		)

		for _, banned := range []string{
			"clean empty upper title area",
			"blank area",
		} {
			if strings.Contains(prompt, banned) {
				t.Fatalf(
					"%s prompt still asks for %q",
					variant.Spec.VariantKey,
					banned,
				)
			}
		}

		// “white panel” 只允许以否定形式出现。
		if strings.Contains(prompt, "white panel") &&
			!strings.Contains(prompt, "no flat white panels") {
			t.Fatalf(
				"%s prompt mentions white panels outside a negation: %s",
				variant.Spec.VariantKey,
				prompt,
			)
		}

		if !strings.Contains(
			prompt,
			"no flat white panels",
		) {
			t.Fatalf(
				"%s prompt lost the no-flat-white-panels constraint",
				variant.Spec.VariantKey,
			)
		}

		if !strings.Contains(
			prompt,
			"same color family",
		) {
			t.Fatalf(
				"%s prompt lost the same-color-family safe zone wording",
				variant.Spec.VariantKey,
			)
		}
	}

	negative := strings.ToLower(
		buildDesignPlanNegativePrompt(plan),
	)

	for _, required := range []string{
		"solid white panel",
		"blank white rectangle",
		"white box",
	} {
		if !strings.Contains(negative, required) {
			t.Fatalf(
				"negative prompt is missing %q: %s",
				required,
				negative,
			)
		}
	}
}

// prompt 里不许出现“标题区/信息区/安全区”这类版式角色词。去掉引号之后
// 第三个候选还在烤字，剩下的诱因就是 prompt 本身在描述一个海报版式——
// 对一个会写字的模型说“这块是标题区”，它就会自己把标题写进去。
// 约束保留（上/下部低细节、同色系），只是改成纯几何的说法。
func TestPromptsNameNoLayoutRoles(
	t *testing.T,
) {
	t.Parallel()

	// 注意：不能禁裸的 "title"/"information"。收尾那句
	// “titles … will be added later by a deterministic layout system”
	// 是负向指令，是要留的。
	banned := []string{
		"title area",
		"title safe",
		"title-safe",
		"information area",
		"information safe",
		"information-safe",
		"caption area",
		"safe zone",
	}

	planner := NewPlanner()

	request := domain.CreatePosterRequest{
		Event: domain.EventBrief{
			Title: "Ritual Night",
		},
	}

	specs, err := planner.Plan(request)
	if err != nil {
		t.Fatalf("plan: %v", err)
	}

	for _, spec := range specs {
		lowered := strings.ToLower(
			planner.BuildPrompt(request, spec),
		)

		for _, fragment := range banned {
			if strings.Contains(lowered, fragment) {
				t.Fatalf(
					"%s prompt names a layout role %q",
					spec.VariantKey,
					fragment,
				)
			}
		}
	}

	plan := testDesignPlan()

	for _, variant := range buildDesignPlanVariants(plan) {
		lowered := strings.ToLower(
			buildDesignPlanPrompt(plan, variant),
		)

		for _, fragment := range banned {
			if strings.Contains(lowered, fragment) {
				t.Fatalf(
					"%s design plan prompt names a layout role %q",
					variant.Spec.VariantKey,
					fragment,
				)
			}
		}
	}
}

// 安全区留空时不能拼出 "upper band  kept low in detail" 这种半截短语。
func TestLowDetailBandSkipsEmptyExtent(
	t *testing.T,
) {
	t.Parallel()

	if got := lowDetailBand("upper", "   "); got != "" {
		t.Fatalf("expected empty band, got %q", got)
	}

	if got := lowDetailBand(
		"lower",
		"bottom_22_percent",
	); got != "lower band bottom_22_percent kept low in detail" {
		t.Fatalf("unexpected band: %q", got)
	}
}

func TestDecodeCandidateSpec(
	t *testing.T,
) {
	t.Parallel()

	if _, ok := decodeCandidateSpec(
		"   ",
	); ok {
		t.Fatal("empty spec JSON should not decode")
	}

	if _, ok := decodeCandidateSpec(
		"{not json",
	); ok {
		t.Fatal("malformed spec JSON should not decode")
	}

	spec, ok := decodeCandidateSpec(
		`{"variantKey":"k","camera":"85mm","palette":["ink black"]}`,
	)
	if !ok {
		t.Fatal("valid spec JSON failed to decode")
	}

	if spec.Camera != "85mm" {
		t.Fatalf("camera = %q", spec.Camera)
	}

	if spec.VariantKey != "k" {
		t.Fatalf("variantKey = %q", spec.VariantKey)
	}
}

// legacy /api/generate 路径的三个内置 spec 也要有各自的镜头。
func TestPlannerSpecsHaveDistinctCameras(
	t *testing.T,
) {
	t.Parallel()

	specs, err := NewPlanner().Plan(
		domain.CreatePosterRequest{
			Event: domain.EventBrief{
				Title: "Ritual Night",
			},
		},
	)
	if err != nil {
		t.Fatalf("plan: %v", err)
	}

	seen := make(map[string]struct{}, len(specs))

	for _, spec := range specs {
		if strings.TrimSpace(spec.Camera) == "" {
			t.Fatalf(
				"%s has no camera",
				spec.VariantKey,
			)
		}

		if _, exists := seen[spec.Camera]; exists {
			t.Fatalf(
				"camera is shared: %q",
				spec.Camera,
			)
		}

		seen[spec.Camera] = struct{}{}
	}
}

// Event.Title 是 composer 的活。它一旦进了 prompt，Z-Image（自带写字能力）
// 就会把标题原文烤进画面，最终和 composer 叠加的标题重影。
// 这里故意把 Visual.Theme 留空，逼出旧的 Event.Title 兜底路径。
func TestPlannerBuildPromptNeverLeaksEventTitle(
	t *testing.T,
) {
	t.Parallel()

	planner := NewPlanner()

	request := domain.CreatePosterRequest{
		Event: domain.EventBrief{
			Title: "混沌冲撞之夜",
		},
	}

	specs, err := planner.Plan(request)
	if err != nil {
		t.Fatalf("plan: %v", err)
	}

	for _, spec := range specs {
		prompt := planner.BuildPrompt(request, spec)

		if strings.Contains(
			prompt,
			request.Event.Title,
		) {
			t.Fatalf(
				"%s prompt leaks the event title: %s",
				spec.VariantKey,
				prompt,
			)
		}
	}
}

// 主题要保留语义（它是真的要画的东西），但不能带引号——
// 引号是“把这段字写出来”的经典信号。
func TestPlannerBuildPromptThemeIsUnquoted(
	t *testing.T,
) {
	t.Parallel()

	planner := NewPlanner()

	const theme = "工业废墟中的仪式"

	request := domain.CreatePosterRequest{
		Event: domain.EventBrief{
			Title: "混沌冲撞之夜",
		},
		Visual: domain.VisualBrief{
			Theme: theme,
		},
	}

	specs, err := planner.Plan(request)
	if err != nil {
		t.Fatalf("plan: %v", err)
	}

	for _, spec := range specs {
		prompt := planner.BuildPrompt(request, spec)

		if !strings.Contains(prompt, theme) {
			t.Fatalf(
				"%s prompt dropped the theme entirely: %s",
				spec.VariantKey,
				prompt,
			)
		}

		if strings.Contains(
			prompt,
			`"`+theme+`"`,
		) {
			t.Fatalf(
				"%s prompt still quotes the theme: %s",
				spec.VariantKey,
				prompt,
			)
		}

		if !strings.Contains(
			prompt,
			"never as text to render",
		) {
			t.Fatalf(
				"%s prompt lost the subject-matter-not-text guard",
				spec.VariantKey,
			)
		}
	}
}

// 烤出来的是中文字形，所以禁令必须点名 CJK，光说 letters 不够。
func TestPromptsBanCJKGlyphs(
	t *testing.T,
) {
	t.Parallel()

	planner := NewPlanner()

	request := domain.CreatePosterRequest{
		Event: domain.EventBrief{
			Title: "Ritual Night",
		},
	}

	specs, err := planner.Plan(request)
	if err != nil {
		t.Fatalf("plan: %v", err)
	}

	for _, spec := range specs {
		lowered := strings.ToLower(
			planner.BuildPrompt(request, spec),
		)

		for _, required := range []string{
			"chinese characters",
			"cjk glyphs",
		} {
			if !strings.Contains(lowered, required) {
				t.Fatalf(
					"%s prompt is missing %q",
					spec.VariantKey,
					required,
				)
			}
		}
	}

	plan := testDesignPlan()

	for _, variant := range buildDesignPlanVariants(plan) {
		lowered := strings.ToLower(
			buildDesignPlanPrompt(plan, variant),
		)

		for _, required := range []string{
			"no chinese characters",
			"no cjk glyphs",
		} {
			if !strings.Contains(lowered, required) {
				t.Fatalf(
					"%s design plan prompt is missing %q",
					variant.Spec.VariantKey,
					required,
				)
			}
		}
	}

	negative := strings.ToLower(
		buildDesignPlanNegativePrompt(plan),
	)

	for _, required := range []string{
		"chinese characters",
		"cjk glyphs",
	} {
		if !strings.Contains(negative, required) {
			t.Fatalf(
				"negative prompt is missing %q: %s",
				required,
				negative,
			)
		}
	}
}

// BuildPrompt 必须把镜头写进 prompt，并且不再要求白色安全区。
func TestPlannerBuildPromptCameraAndNoWhitePanel(
	t *testing.T,
) {
	t.Parallel()

	planner := NewPlanner()

	request := domain.CreatePosterRequest{
		Event: domain.EventBrief{
			Title: "Ritual Night",
		},
	}

	specs, err := planner.Plan(request)
	if err != nil {
		t.Fatalf("plan: %v", err)
	}

	for _, spec := range specs {
		prompt := planner.BuildPrompt(request, spec)

		if !strings.Contains(prompt, spec.Camera) {
			t.Fatalf(
				"%s prompt is missing the camera",
				spec.VariantKey,
			)
		}

		lowered := strings.ToLower(prompt)

		if !strings.Contains(
			lowered,
			"never a flat white panel",
		) {
			t.Fatalf(
				"%s prompt lost the no-white-panel constraint",
				spec.VariantKey,
			)
		}

		if !strings.Contains(
			lowered,
			"same color family",
		) {
			t.Fatalf(
				"%s prompt lost the same-color-family wording",
				spec.VariantKey,
			)
		}
	}
}

// 十六进制色值绝不能进 prompt。LLM 按 schema 返回 #8B171E，直接拼进正向词
// 会被 Z-Image 当成要写的字符串——实测顶部烤出了 "8B171e / 080101 / 215%"。
func TestDesignPlanPromptHasNoHexColors(
	t *testing.T,
) {
	t.Parallel()

	plan := testDesignPlan()

	plan.Palette = []string{
		"#080101",
		"#2d0505",
		"#8B171E",
		"#fff",
		"ink black",
	}

	for _, variant := range buildDesignPlanVariants(plan) {
		prompt := buildDesignPlanPrompt(plan, variant)

		if strings.Contains(prompt, "#") {
			t.Fatalf(
				"%s prompt still carries a hex color: %s",
				variant.Spec.VariantKey,
				prompt,
			)
		}

		for _, leaked := range []string{
			"8B171E",
			"8b171e",
			"080101",
			"2d0505",
		} {
			if strings.Contains(prompt, leaked) {
				t.Fatalf(
					"%s prompt leaks hex digits %q",
					variant.Spec.VariantKey,
					leaked,
				)
			}
		}

		// 语义不能丢：色值要翻成模型看得懂的措辞。
		if !strings.Contains(prompt, "ink black") {
			t.Fatalf(
				"%s prompt dropped the named color: %s",
				variant.Spec.VariantKey,
				prompt,
			)
		}
	}

	// 结构化 spec 里必须保留原始 hex，前端要拿它画色板。
	for _, variant := range buildDesignPlanVariants(plan) {
		if !strings.Contains(
			strings.Join(variant.Spec.Palette, ","),
			"#8B171E",
		) {
			t.Fatalf(
				"%s spec lost the original hex palette",
				variant.Spec.VariantKey,
			)
		}
	}
}

func TestDescribeColor(
	t *testing.T,
) {
	t.Parallel()

	for input, want := range map[string]string{
		"#000000":   "near-black",
		"#ffffff":   "near-white",
		"#808080":   "mid-tone grey",
		"#8B171E":   "deep red",
		"ink black": "ink black",
		"#zzzzzz":   "#zzzzzz",
	} {
		if got := describeColor(input); got != want {
			t.Fatalf(
				"describeColor(%q) = %q, want %q",
				input,
				got,
				want,
			)
		}
	}
}

func TestDescribeColorHues(
	t *testing.T,
) {
	t.Parallel()

	for input, want := range map[string]string{
		"#8B171E": "deep red",
		"#E8A020": "mid-tone amber",
		"#1E7A32": "deep green",
		"#1E3A8A": "deep blue",
		"#7A1E8A": "deep violet",
		"#F0C0E0": "pale magenta",
		"#101010": "near-black",
	} {
		if got := describeColor(input); got != want {
			t.Fatalf(
				"describeColor(%q) = %q, want %q",
				input,
				got,
				want,
			)
		}
	}
}
