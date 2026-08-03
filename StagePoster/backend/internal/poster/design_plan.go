package poster

import (
	"context"
	"errors"
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

type designPlanVariant struct {
	Spec           domain.CandidateSpec
	PromptAddition string
}

func (s *Service) CreateFromDesignPlan(
	ctx context.Context,
	request domain.CreatePosterRequest,
	plan domain.DesignPlan,
) (domain.PosterResponse, error) {
	request.Event.Title = strings.TrimSpace(
		request.Event.Title,
	)

	if request.Event.Title == "" {
		return domain.PosterResponse{},
			fmt.Errorf(
				"%w: event title is required",
				ErrInvalidPosterBrief,
			)
	}

	if strings.TrimSpace(plan.PositivePrompt) == "" {
		return domain.PosterResponse{},
			fmt.Errorf(
				"%w: design plan positive prompt is required",
				ErrInvalidPosterBrief,
			)
	}

	if strings.TrimSpace(request.Visual.Style) == "" {
		request.Visual.Style = plan.ComposerTemplate
	}

	variants := buildDesignPlanVariants(plan)

	if len(variants) != 3 {
		return domain.PosterResponse{},
			errors.New(
				"design plan must produce exactly 3 candidates",
			)
	}

	posterID, err := domain.NewID("poster_")
	if err != nil {
		return domain.PosterResponse{}, err
	}

	goal := domain.GoalContract{
		Width:               1024,
		Height:              1536,
		AllowPeople:         false,
		AllowReadableText:   false,
		RequireCentralMotif: true,
		MaxAttempts:         2,
	}

	eventJSON, err := marshalJSON(request.Event)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	brandingJSON, err := marshalJSON(request.Branding)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	visualJSON, err := marshalJSON(request.Visual)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	goalJSON, err := marshalJSON(goal)
	if err != nil {
		return domain.PosterResponse{}, err
	}

	now := time.Now().UTC()

	posterRecord := domain.PosterRecord{
		ID:           posterID,
		Status:       domain.PosterStatusPlanning,
		StyleKey:     request.Visual.Style,
		EventJSON:    eventJSON,
		BrandingJSON: brandingJSON,
		VisualJSON:   visualJSON,
		GoalJSON:     goalJSON,
		CreatedAt:    now,
		UpdatedAt:    now,
	}

	if err := s.repository.CreatePoster(
		ctx,
		posterRecord,
	); err != nil {
		return domain.PosterResponse{}, err
	}

	baseSeed := time.Now().UnixNano() &
		0x7fffffffffffffff

	for index, variant := range variants {
		compiledPrompt := buildDesignPlanPrompt(
			plan,
			variant,
		)

		seed := baseSeed +
			int64((index+1)*100003)

		generation, err := s.core.Generate(
			ctx,
			applyReferenceControl(
				domain.GenerateRequest{
					Prompt: compiledPrompt,
					NegativePrompt: buildDesignPlanNegativePrompt(
						plan,
					),
					Seed: &seed,
				},
				request.Visual,
			),
		)
		if err != nil {
			_ = s.repository.UpdatePosterStatus(
				context.Background(),
				posterID,
				domain.PosterStatusFailed,
				err.Error(),
			)

			return domain.PosterResponse{}, err
		}

		candidateID, err := domain.NewID("candidate_")
		if err != nil {
			return domain.PosterResponse{}, err
		}

		specJSON, err := marshalJSON(variant.Spec)
		if err != nil {
			return domain.PosterResponse{}, err
		}

		candidateNow := time.Now().UTC()

		candidate := domain.CandidateRecord{
			ID:             candidateID,
			PosterID:       posterID,
			JobID:          generation.JobID,
			VariantIndex:   index,
			VariantKey:     variant.Spec.VariantKey,
			VariantName:    variant.Spec.VariantName,
			SpecJSON:       specJSON,
			CompiledPrompt: compiledPrompt,
			Seed:           seed,
			Attempt:        1,
			Status:         domain.CandidateStatusGenerating,
			Passed:         false,
			Selected:       false,
			CreatedAt:      candidateNow,
			UpdatedAt:      candidateNow,
		}

		if err := s.repository.CreateCandidate(
			ctx,
			candidate,
		); err != nil {
			_ = s.repository.UpdatePosterStatus(
				context.Background(),
				posterID,
				domain.PosterStatusFailed,
				err.Error(),
			)

			return domain.PosterResponse{}, err
		}
	}

	if err := s.repository.UpdatePosterStatus(
		ctx,
		posterID,
		domain.PosterStatusGenerating,
		"",
	); err != nil {
		return domain.PosterResponse{}, err
	}

	return s.Get(ctx, posterID)
}

func buildDesignPlanVariants(
	plan domain.DesignPlan,
) []designPlanVariant {
	palette := append(
		[]string(nil),
		plan.Palette...,
	)

	// 安全区是三个候选共享的排版约束；主体取景、镜头、材质和配色
	// 侧重必须彼此拉开，否则三张候选看上去几乎是同一张图。
	//
	// 措辞刻意只描述几何位置和细节密度，不出现 title / information —— 对
	// 一个会写字的模型说"这里是标题区"，它就会往里填字。
	safeZones := strings.Join(
		nonEmptyPromptFragments([]string{
			lowDetailBand(
				"upper",
				plan.Composition.TitleSafeZone,
			),
			lowDetailBand(
				"lower",
				plan.Composition.InformationSafeZone,
			),
		}),
		", ",
	)

	subject := strings.TrimSpace(plan.Composition.Subject)
	if subject == "" {
		subject = strings.TrimSpace(plan.Concept)
	}

	symmetry := strings.TrimSpace(plan.Composition.Symmetry)
	if symmetry == "" {
		symmetry = "central symmetry"
	}

	return []designPlanVariant{
		{
			Spec: domain.CandidateSpec{
				VariantKey: plan.ID + "-balanced",
				VariantName: plan.Name +
					" · Balanced",
				Motif: subject +
					", rendered as one coherent central emblem at mid distance",
				Composition: joinComposition(
					symmetry+", balanced mid-field placement, subject fully contained with even margins",
					safeZones,
				),
				Camera: "straight-on medium full shot at eye level, 50mm equivalent, natural perspective, subject occupying the middle field",
				Materials: []string{
					"cinematic editorial texture",
					"fine printed grain",
					"professional concert poster finish",
				},
				Palette:  palette,
				Lighting: "balanced cinematic lighting with controlled contrast and open midtones",
			},
			PromptAddition: "balanced editorial interpretation, clear central hierarchy, controlled cinematic contrast, full tonal range",
		},
		{
			Spec: domain.CandidateSpec{
				VariantKey: plan.ID + "-dramatic",
				VariantName: plan.Name +
					" · Dramatic",
				Motif: subject +
					", rendered as a towering monumental structure seen from below, cropped tightly at the frame edges",
				Composition: joinComposition(
					"off-center low-angle monumental framing, subject breaking past the upper third, compressed foreground depth",
					safeZones,
				),
				Camera: "low-angle telephoto close crop, 85mm equivalent, compressed depth of field, worm's-eye perspective looking up at the subject",
				Materials: []string{
					"high-contrast cinematic texture",
					"heavy atmospheric haze",
					"rich volumetric depth",
				},
				Palette: appendPaletteEmphasis(
					palette,
					"deepened shadow tones, one saturated accent carrying the highlight",
				),
				Lighting: "dramatic directional rim lighting with deep dimensional shadows and strong falloff",
			},
			PromptAddition: "dramatic low-angle monumentality, tight crop, strong depth layering, heavy shadow, single burning accent light",
		},
		{
			Spec: domain.CandidateSpec{
				VariantKey: plan.ID + "-graphic",
				VariantName: plan.Name +
					" · Graphic",
				Motif: subject +
					", reduced to a bold flat silhouette emblem with minimal internal detail",
				Composition: joinComposition(
					"flat frontal graphic layout, small subject isolated in generous negative space, poster-first geometry",
					safeZones,
				),
				Camera: "wide flat-on graphic framing, 28mm equivalent, minimal perspective distortion, subject small and centered with large surrounding field",
				Materials: []string{
					"refined graphic poster treatment",
					"flat screen-print ink",
					"clean silhouette separation",
				},
				Palette: appendPaletteEmphasis(
					palette,
					"flat two-tone reduction with a single contrasting accent",
				),
				Lighting: "even graphic lighting with hard silhouette edges and almost no gradient",
			},
			PromptAddition: "flat graphic silhouette, generous negative space, reduced detail, screen-print poster language, poster-first readability",
		},
	}
}

func lowDetailBand(
	edge string,
	extent string,
) string {
	extent = strings.TrimSpace(extent)

	if extent == "" {
		return ""
	}

	return edge +
		" band " +
		extent +
		" kept low in detail"
}

func joinComposition(
	framing string,
	safeZones string,
) string {
	return strings.Join(
		nonEmptyPromptFragments([]string{
			framing,
			safeZones,
		}),
		", ",
	)
}

func appendPaletteEmphasis(
	palette []string,
	emphasis string,
) []string {
	result := append(
		[]string(nil),
		palette...,
	)

	return append(result, emphasis)
}

// hexColorPattern 匹配 #RGB / #RRGGBB 形式的色值。
var hexColorPattern = regexp.MustCompile(
	`#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b`,
)

// describeColor 把 #8B171E 这类色值翻成自然语言。
//
// 设计方案的 palette 是给人和前端看的十六进制，但它会被原样拼进图像
// prompt——而 Z-Image 会写字，于是把 "8B171e" 当成要画的字符串烤进海报
// 顶部。色值必须先翻译成模型真正理解的措辞。
func describeColor(
	value string,
) string {
	value = strings.TrimSpace(value)

	if !hexColorPattern.MatchString(value) {
		return value
	}

	hex := strings.TrimPrefix(value, "#")

	if len(hex) == 3 {
		hex = string([]byte{
			hex[0], hex[0],
			hex[1], hex[1],
			hex[2], hex[2],
		})
	}

	parsed, err := strconv.ParseUint(hex, 16, 32)
	if err != nil {
		return ""
	}

	red := float64(parsed >> 16 & 0xff)
	green := float64(parsed >> 8 & 0xff)
	blue := float64(parsed & 0xff)

	max := math.Max(red, math.Max(green, blue))
	min := math.Min(red, math.Min(green, blue))

	lightness := (max + min) / 2 / 255

	tone := "mid-tone"

	switch {
	case lightness < 0.10:
		tone = "near-black"

	case lightness < 0.35:
		tone = "deep"

	case lightness > 0.85:
		tone = "near-white"

	case lightness > 0.68:
		tone = "pale"
	}

	// 饱和度太低就只是灰阶，硬套色相名会误导模型。
	if max-min < 18 {
		switch tone {
		case "near-black":
			return "near-black"

		case "near-white":
			return "near-white"

		default:
			return tone + " grey"
		}
	}

	// 走标准 HSL 色相角。按 R/G/B 大小关系分类看似简单，但 (139,23,30)
	// 这种明显的暗红会被判成洋红。
	span := max - min

	var degrees float64

	switch max {
	case red:
		degrees = math.Mod(
			(green-blue)/span,
			6,
		) * 60

	case green:
		degrees = ((blue-red)/span + 2) * 60

	default:
		degrees = ((red-green)/span + 4) * 60
	}

	if degrees < 0 {
		degrees += 360
	}

	hue := "red"

	switch {
	case degrees < 16 || degrees >= 345:
		hue = "red"

	case degrees < 45:
		hue = "amber"

	case degrees < 70:
		hue = "yellow"

	case degrees < 160:
		hue = "green"

	case degrees < 200:
		hue = "teal"

	case degrees < 255:
		hue = "blue"

	case degrees < 300:
		hue = "violet"

	default:
		hue = "magenta"
	}

	return tone + " " + hue
}

// describePalette 把整条 palette 翻成自然语言并去重。
func describePalette(
	palette []string,
) []string {
	described := make(
		[]string,
		0,
		len(palette),
	)

	for _, entry := range palette {
		if converted := describeColor(
			entry,
		); converted != "" {
			described = append(described, converted)
		}
	}

	return nonEmptyPromptFragments(described)
}

func buildDesignPlanPrompt(
	plan domain.DesignPlan,
	variant designPlanVariant,
) string {
	// 安全区不能靠画一块纯白色块来实现——那会毁掉整张海报。正确做法是
	// 要求该区域低细节、与画面同色系，文字由 composer 叠加。
	//
	// 这里也不提 title / information：模型看不到 composer，只看到 prompt，
	// 一旦告诉它某块是"标题区"，它就会自己写标题。
	fragments := []string{
		strings.TrimSpace(plan.PositivePrompt),
		strings.TrimSpace(variant.PromptAddition),
		"professional vertical 2:3 music event key visual",
		"one coherent visual concept",
		strings.TrimSpace(variant.Spec.Motif),
		strings.TrimSpace(variant.Spec.Composition),
		strings.TrimSpace(variant.Spec.Camera),
		strings.Join(variant.Spec.Materials, ", "),
		strings.Join(
			describePalette(variant.Spec.Palette),
			", ",
		),
		strings.TrimSpace(variant.Spec.Lighting),
		"upper region kept low in detail with soft tonal gradient in the same color family as the artwork",
		"lower region kept low in detail with quiet tonal background in the same color family",
		"no flat white panels",
		"no readable text",
		"no letters",
		"no words",
		"no chinese characters",
		"no CJK glyphs",
		"no logos",
		"no watermarks",
	}

	return strings.Join(
		nonEmptyPromptFragments(fragments),
		", ",
	)
}

func buildDesignPlanNegativePrompt(
	plan domain.DesignPlan,
) string {
	fragments := []string{
		strings.TrimSpace(plan.NegativePrompt),
		"solid white panel",
		"blank white rectangle",
		"white box",
		"white banner strip",
		"pure white background block",
		"text",
		"letters",
		"words",
		"captions",
		"typography",
		"chinese characters",
		"CJK glyphs",
		"gibberish",
		"logos",
		"watermarks",
		"signage",
		"UI",
		"mockup",
		"low resolution",
	}

	return strings.Join(
		nonEmptyPromptFragments(fragments),
		", ",
	)
}

func nonEmptyPromptFragments(
	values []string,
) []string {
	result := make(
		[]string,
		0,
		len(values),
	)

	seen := make(map[string]struct{})

	for _, value := range values {
		value = strings.TrimSpace(value)

		if value == "" {
			continue
		}

		key := strings.ToLower(value)

		if _, exists := seen[key]; exists {
			continue
		}

		seen[key] = struct{}{}
		result = append(result, value)
	}

	return result
}
